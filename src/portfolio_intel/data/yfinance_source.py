"""yfinance implementation of DataSource.

yfinance is unofficial and can break with upstream Yahoo changes. Keep all
yfinance imports and quirks inside this file so swapping providers (Finnhub,
Zerodha Kite, Upstox) requires no edits elsewhere.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from ..markets import Market
from .base import DataSource, DataSourceError
from .models import NewsItem, Quote


class YFinanceSource(DataSource):
    # yfinance covers all three of these via ticker suffixes.
    _SUPPORTED = {Market.US, Market.NSE, Market.BSE}

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
        # returns mostly-empty dicts for Indian tickers.
        try:
            fi = ticker.fast_info
            price = _coerce_float(getattr(fi, "last_price", None))
            prev_close = _coerce_float(getattr(fi, "previous_close", None))
            currency = getattr(fi, "currency", None) or market.currency
        except Exception as e:  # yfinance can raise a variety of network errors
            raise DataSourceError(f"fast_info failed for {qualified}: {e}") from e

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
        try:
            return ticker.history(period=period, interval=interval, auto_adjust=False)
        except Exception:
            return None


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


def _market_is_likely_closed(market: Market, now_utc: datetime) -> bool:
    """Cheap heuristic so quotes can be labeled 'stale' when shown outside
    trading hours. Not a holiday-aware calendar — intentional: this is a
    label, not a trading gate. A real calendar comes later if needed."""
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        return False
    local = now_utc.astimezone(ZoneInfo(market.timezone))
    if local.weekday() >= 5:
        return True
    minutes = local.hour * 60 + local.minute
    if market is Market.US:
        return not (9 * 60 + 30 <= minutes <= 16 * 60)
    if market in (Market.NSE, Market.BSE):
        return not (9 * 60 + 15 <= minutes <= 15 * 60 + 30)
    return False
