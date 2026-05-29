"""yfinance implementation of DataSource.

yfinance is unofficial and can break with upstream Yahoo changes. Keep all
yfinance imports and quirks inside this file so swapping providers (Finnhub,
Zerodha Kite, Upstox) requires no edits elsewhere.
"""
from __future__ import annotations

import random
import time
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from ..markets import Market
from .base import DataSource, DataSourceError
from .models import NewsItem, Quote


class YFinanceSource(DataSource):
    # yfinance covers all three of these via ticker suffixes.
    _SUPPORTED = {Market.US, Market.NSE, Market.BSE, Market.DFM, Market.ADX}

    def __init__(self) -> None:
        try:
            import yfinance  # noqa: F401
        except ImportError as e:
            raise DataSourceError(
                "yfinance is not installed. Run: pip install -e ."
            ) from e

    def supports(self, market: Market) -> bool:
        return market in self._SUPPORTED

    def _ticker(self, symbol: str, market: Market):
        import yfinance as yf

        qualified = market.format_ticker(symbol)
        return yf.Ticker(qualified), qualified

    def get_quote(self, symbol: str, market: Market) -> Quote:
        if not self.supports(market):
            raise DataSourceError(f"market {market.code} not supported by yfinance source")

        ticker, qualified = self._ticker(symbol, market)

        # fast_info is cheaper and more reliable than .info, which sometimes
        # returns mostly-empty dicts for Indian tickers. Retry with backoff —
        # Yahoo throttles during burst refreshes. The history fallback below
        # picks up if fast_info still has no price after retries.
        price = prev_close = None
        currency = market.currency
        for attempt in range(4):
            try:
                fi = ticker.fast_info
                price = _coerce_float(getattr(fi, "last_price", None))
                prev_close = _coerce_float(getattr(fi, "previous_close", None))
                currency = getattr(fi, "currency", None) or market.currency
            except Exception:
                pass
            if price is not None:
                break
            if attempt < 3:
                time.sleep((0.6 * (2 ** attempt)) + random.uniform(0, 0.3))

        # Fall back to 1-day history when fast_info gives us nothing.
        if price is None:
            hist = self._safe_history(ticker, period="5d", interval="1d")
            if hist is None or hist.empty:
                raise DataSourceError(f"no quote available for {qualified}")
            price = float(hist["Close"].iloc[-1])
            if prev_close is None and len(hist) >= 2:
                prev_close = float(hist["Close"].iloc[-2])

        as_of = datetime.now(timezone.utc)
        stale = _market_is_likely_closed(market, as_of)

        return Quote(
            symbol=symbol.upper(),
            market_code=market.code,
            price=float(price),
            currency=currency,
            as_of=as_of,
            previous_close=prev_close,
            stale=stale,
        )

    def get_quotes_bulk(self, items: list[tuple[str, Market]]) -> dict[tuple[str, str], Quote]:
        """Fetch many quotes for the live-tile path. Returns a
        {(symbol_upper, market_code): Quote} map; missing tickers are omitted.

        Strategy:
          1. Single bulk yf.download() — one HTTP round trip for all tickers.
             During market hours the "today" daily-close row updates with
             the current quote within the session, so this gives us live
             prices without per-ticker calls.
          2. For tickers the bulk call missed (Yahoo throttles, exchange
             quirks, etc.) — fall back to per-ticker fast_info, capped at
             a small batch so the whole call stays well under the poll
             interval.

        A previous version called fast_info for every open-market ticker
        on top of the bulk; that turns one HTTP call into N and easily
        runs past the 30s poll interval with a few dozen holdings — which
        is exactly why the dashboard's "live · 1m ago" timestamp got
        stuck.
        """
        import yfinance as yf

        if not items:
            return {}

        qualified_to_key: dict[str, tuple[str, str]] = {}
        market_by_qualified: dict[str, Market] = {}
        for sym, mkt in items:
            qualified = mkt.format_ticker(sym)
            qualified_to_key[qualified] = (sym.upper(), mkt.code)
            market_by_qualified[qualified] = mkt

        out: dict[tuple[str, str], Quote] = {}
        as_of = datetime.now(timezone.utc)
        missing: list[str] = []

        try:
            df = yf.download(
                tickers=list(qualified_to_key.keys()),
                # Use 5d (not 2d) — yfinance during market hours sometimes
                # returns just the current intraday row, which would leave
                # `previous_close` empty for the day-change calc. 5d
                # guarantees at least one prior session is available even
                # if today's bar hasn't finalised.
                period="5d",
                interval="1d",
                auto_adjust=False,
                progress=False,
                group_by="ticker",
                threads=True,
            )
        except Exception:
            df = None

        single = len(qualified_to_key) == 1
        for qualified, key in qualified_to_key.items():
            closes = None
            if df is not None and not df.empty:
                try:
                    closes = df["Close"].dropna() if single else df[qualified]["Close"].dropna()
                except (KeyError, AttributeError):
                    closes = None
            if closes is None or closes.empty:
                missing.append(qualified)
                continue
            price = float(closes.iloc[-1])
            prev = float(closes.iloc[-2]) if len(closes) >= 2 else None
            market = market_by_qualified[qualified]
            # When yfinance still didn't give us a previous close (one-row
            # response or weird MultiIndex), try fast_info as a fallback —
            # the per-ticker cost is tolerable here because we only hit it
            # for the affected rows, not the whole portfolio.
            if prev is None:
                try:
                    t = yf.Ticker(qualified)
                    prev = _coerce_float(getattr(t.fast_info, "previous_close", None))
                except Exception:
                    prev = None
            out[key] = Quote(
                symbol=key[0],
                market_code=market.code,
                price=price,
                currency=market.currency,
                as_of=as_of,
                previous_close=prev,
                stale=_market_is_likely_closed(market, as_of),
            )

        # Per-ticker fallback ONLY for what bulk genuinely missed. Capped so
        # a wave of misses can't blow the budget.
        _FALLBACK_CAP = 10
        for qualified in missing[:_FALLBACK_CAP]:
            key = qualified_to_key[qualified]
            market = market_by_qualified[qualified]
            try:
                t = yf.Ticker(qualified)
                fi = t.fast_info
                price = _coerce_float(getattr(fi, "last_price", None))
                prev = _coerce_float(getattr(fi, "previous_close", None))
                if price is None:
                    continue
                out[key] = Quote(
                    symbol=key[0],
                    market_code=market.code,
                    price=float(price),
                    currency=getattr(fi, "currency", None) or market.currency,
                    as_of=as_of,
                    previous_close=prev,
                    stale=_market_is_likely_closed(market, as_of),
                )
            except Exception:
                continue

        return out

    def get_history(
        self,
        symbol: str,
        market: Market,
        period: str = "1y",
        interval: str = "1d",
    ) -> pd.DataFrame:
        if not self.supports(market):
            raise DataSourceError(f"market {market.code} not supported by yfinance source")
        ticker, qualified = self._ticker(symbol, market)
        df = self._safe_history(ticker, period=period, interval=interval)
        if df is None or df.empty:
            raise DataSourceError(f"no history available for {qualified}")
        df = df.rename(
            columns={
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Volume": "volume",
            }
        )
        return df[["open", "high", "low", "close", "volume"]]

    def get_news(self, symbol: str, market: Market) -> list[NewsItem]:
        if not self.supports(market):
            return []
        ticker, _ = self._ticker(symbol, market)
        try:
            raw = ticker.news or []
        except Exception:
            return []
        out: list[NewsItem] = []
        for item in raw:
            # yfinance has reshaped this payload more than once; tolerate both shapes.
            content = item.get("content", item) if isinstance(item, dict) else {}
            title = content.get("title") or item.get("title") if isinstance(item, dict) else None
            if not title:
                continue
            publisher = (
                (content.get("provider") or {}).get("displayName")
                if isinstance(content.get("provider"), dict)
                else item.get("publisher") if isinstance(item, dict) else None
            ) or "unknown"
            url = (
                (content.get("canonicalUrl") or {}).get("url")
                if isinstance(content.get("canonicalUrl"), dict)
                else item.get("link") if isinstance(item, dict) else None
            ) or ""
            published_at = _parse_news_time(item)
            out.append(
                NewsItem(
                    title=title,
                    publisher=publisher,
                    url=url,
                    published_at=published_at,
                    summary=content.get("summary") if isinstance(content, dict) else None,
                )
            )
        return out

    @staticmethod
    def _safe_history(ticker, period: str, interval: str) -> Optional[pd.DataFrame]:
        # Yahoo throttles aggressively when many tickers are fetched in tight
        # sequence (the dashboard refresh path can hit 70+). On empty/error,
        # back off and retry a few times — non-fatal if all attempts fail.
        for attempt in range(4):
            try:
                df = ticker.history(period=period, interval=interval, auto_adjust=False)
            except Exception:
                df = None
            if df is not None and not df.empty:
                return df
            if attempt < 3:
                time.sleep((0.6 * (2 ** attempt)) + random.uniform(0, 0.3))
        return df


def _coerce_float(v) -> Optional[float]:
    try:
        if v is None:
            return None
        f = float(v)
        if f != f:  # NaN
            return None
        return f
    except (TypeError, ValueError):
        return None


def _parse_news_time(item) -> Optional[datetime]:
    if not isinstance(item, dict):
        return None
    ts = item.get("providerPublishTime")
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    pub = item.get("content", {}).get("pubDate") if isinstance(item.get("content"), dict) else None
    if isinstance(pub, str):
        try:
            return datetime.fromisoformat(pub.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def is_market_open(market: Market, now_utc: Optional[datetime] = None) -> bool:
    """Inverse of _market_is_likely_closed, exposed for the live-quote path."""
    now_utc = now_utc or datetime.now(timezone.utc)
    return not _market_is_likely_closed(market, now_utc)


def _market_is_likely_closed(market: Market, now_utc: datetime) -> bool:
    """Cheap heuristic so quotes can be labeled 'stale' when shown outside
    trading hours. Not a holiday-aware calendar — intentional: this is a
    label, not a trading gate. A real calendar comes later if needed.

    Weekend logic is market-specific: US/India follow Sat-Sun off; UAE
    markets trade Sun-Thu and are closed Fri-Sat.
    """
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        return False
    local = now_utc.astimezone(ZoneInfo(market.timezone))
    wd = local.weekday()  # Mon=0 ... Sun=6
    minutes = local.hour * 60 + local.minute

    if market is Market.US:
        if wd >= 5:  # Sat (5), Sun (6) — closed
            return True
        return not (9 * 60 + 30 <= minutes <= 16 * 60)

    if market in (Market.NSE, Market.BSE):
        if wd >= 5:  # Sat, Sun — closed
            return True
        return not (9 * 60 + 15 <= minutes <= 15 * 60 + 30)

    if market in (Market.DFM, Market.ADX):
        # UAE markets: trading week is Sun-Thu (wd 6, 0, 1, 2, 3).
        # Closed Fri (4) and Sat (5).
        if wd in (4, 5):
            return True
        # DFM/ADX: ~10:00-15:00 Gulf Standard Time (UTC+4).
        return not (10 * 60 <= minutes <= 15 * 60)

    # Unknown market — treat as closed to be conservative. Better to
    # under-poll than show "live" for a market we have no rules for.
    return True
