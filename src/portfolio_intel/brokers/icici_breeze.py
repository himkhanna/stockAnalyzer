"""ICICI Direct Breeze API — read-only wrapper.

We deliberately expose ONLY two operations:
- `connect()`: exchange the user's daily session token for an authenticated
  client.
- `get_holdings()`: pull current portfolio holdings.

No order placement. No fund transfer. No watchlist mutation. If we ever
add execution, it goes through a separate, explicitly-opted-in module so
the read-only path can't accidentally place an order.

Auth flow Breeze requires (one-time-per-day):
  1. User goes to https://api.icicidirect.com/apiuser/login?api_key=<urlencoded>
  2. After logging in, ICICI redirects to a URL with ?apisession=XXX
  3. The user pastes XXX into our UI as the session token
  4. We call breeze.generate_session(api_secret, session_token)
  5. Session is valid until the next midnight IST
"""
from __future__ import annotations

import sys
import time
import urllib.parse
from dataclasses import dataclass
from datetime import date, datetime, time as _time_mod, timedelta, timezone
from typing import Optional


class BreezeError(Exception):
    """Generic Breeze problem."""


class BreezeNotInstalled(BreezeError):
    """breeze-connect isn't installed. Install with: pip install -e '.[brokers]'"""


class BreezeNotConnected(BreezeError):
    """No active session — credentials missing or session token never generated."""


class BreezeSessionExpired(BreezeError):
    """Session expired (Breeze sessions die at midnight IST). Reconnect."""


def _import_breeze_with_retry(max_attempts: int = 3):
    """Import breeze_connect.BreezeConnect, retrying on the flaky
    SecurityMaster.zip download.

    The SDK fetches a 3MB+ master file at MODULE IMPORT TIME. ICICI's
    CDN occasionally truncates the response (http.client.IncompleteRead),
    which bubbles out as a non-ImportError exception during the import
    statement. Python doesn't cache a failed module load, so retrying
    just works — we add a small backoff between attempts.
    """
    last_err: Optional[BaseException] = None
    for attempt in range(max_attempts):
        try:
            from breeze_connect import BreezeConnect  # type: ignore
            return BreezeConnect
        except ImportError as e:
            # Genuine "not installed" — don't retry.
            raise BreezeNotInstalled(
                "breeze-connect is not installed. Run: pip install -e '.[brokers]'"
            ) from e
        except Exception as e:
            last_err = e
            # Best-effort cleanup of any partial state so the next
            # import doesn't reuse a half-loaded module.
            for mod_name in [m for m in sys.modules if m.startswith("breeze_connect")]:
                sys.modules.pop(mod_name, None)
            if attempt < max_attempts - 1:
                time.sleep(0.8 * (attempt + 1))

    raise BreezeError(
        "ICICI SDK init failed after retries — typically a truncated "
        f"SecurityMaster.zip download from icicidirect.com. Try again "
        f"shortly or restart the backend. Last error: "
        f"{type(last_err).__name__ if last_err else 'unknown'}: {last_err}"
    ) from last_err


@dataclass(frozen=True)
class BrokerHolding:
    """A holding as the broker reports it, before we translate into our canonical schema."""
    stock_code: str          # broker-internal code (e.g. EXIIND)
    exchange_code: str       # "NSE" or "BSE"
    quantity: float
    average_price: float
    current_price: Optional[float]
    isin: str
    company_name: Optional[str] = None
    exchange_stock_code: Optional[str] = None  # the real NSE/BSE ticker (e.g. EXIDEIND), from get_names()
    raw: dict | None = None


@dataclass(frozen=True)
class OptionContract:
    """A single option row from the NSE chain."""
    stock_code: str           # ICICI's underlying code
    expiry_date: str          # ISO date "YYYY-MM-DD"
    strike_price: float
    right: str                # "call" or "put"
    bid: Optional[float]
    ask: Optional[float]
    ltp: Optional[float]      # last traded price
    open_interest: Optional[float]
    volume: Optional[float]
    raw: dict | None = None


# IST = UTC+05:30
_IST = timezone(timedelta(hours=5, minutes=30))


def login_url(api_key: str) -> str:
    """The URL the user opens in their browser to start the OAuth flow."""
    return f"https://api.icicidirect.com/apiuser/login?api_key={urllib.parse.quote_plus(api_key)}"


def next_session_expiry(now: Optional[datetime] = None) -> datetime:
    """Breeze sessions die at midnight IST. Return the expiry timestamp (UTC)."""
    now = now or datetime.now(tz=timezone.utc)
    now_ist = now.astimezone(_IST)
    expiry_ist = datetime.combine(now_ist.date() + timedelta(days=1), _time_mod.min, tzinfo=_IST)
    return expiry_ist.astimezone(timezone.utc)


class BreezeClient:
    """Thin wrapper around breeze_connect.BreezeConnect.

    Created in two phases so we can persist intermediate state:
    - `BreezeClient(api_key)` instantiates the SDK
    - `client.connect(api_secret, session_token)` authenticates
    """

    def __init__(self, api_key: str) -> None:
        BreezeConnect = _import_breeze_with_retry()
        self.api_key = api_key
        try:
            self._sdk = BreezeConnect(api_key=api_key)
        except Exception as e:
            raise BreezeError(
                f"BreezeConnect instantiation failed: "
                f"{type(e).__name__}: {e}"
            ) from e

    def connect(self, api_secret: str, session_token: str) -> None:
        """Exchange a fresh session token for an authenticated client.

        Raises BreezeError if Breeze rejects the token (most often: token
        already used, or token belongs to a different api_key)."""
        try:
            self._sdk.generate_session(api_secret=api_secret, session_token=session_token)
        except Exception as e:
            raise BreezeError(f"Breeze rejected the session token: {e}") from e

    def get_holdings(self) -> list[BrokerHolding]:
        """Pull holdings across all Indian equity exchanges Breeze covers."""
        holdings: list[BrokerHolding] = []
        seen: set[tuple[str, str]] = set()  # de-dupe across exchanges by (isin, stock_code)
        last_error: Optional[Exception] = None

        for exchange in ("NSE", "BSE"):
            try:
                resp = self._sdk.get_portfolio_holdings(exchange_code=exchange)
            except Exception as e:
                msg = str(e).lower()
                if "session" in msg or "auth" in msg or "expired" in msg:
                    raise BreezeSessionExpired(str(e)) from e
                last_error = e
                continue

            if not isinstance(resp, dict):
                last_error = BreezeError(
                    f"unexpected Breeze response shape: {type(resp).__name__}"
                )
                continue

            err = resp.get("Error") or resp.get("error")
            if err:
                msg = str(err).lower()
                if "session" in msg or "auth" in msg:
                    raise BreezeSessionExpired(str(err))
                # "no holdings" is reported as an Error string for some accounts;
                # don't fail the whole sync just because one exchange is empty.
                if "no" in msg and ("data" in msg or "holding" in msg or "record" in msg):
                    continue
                last_error = BreezeError(str(err))
                continue

            records = resp.get("Success") or resp.get("success") or []
            if not isinstance(records, list):
                continue

            for r in records:
                if not isinstance(r, dict):
                    continue
                try:
                    h = _parse_holding(r)
                except (ValueError, TypeError):
                    continue
                if not h.exchange_code:
                    h = BrokerHolding(
                        stock_code=h.stock_code,
                        exchange_code=exchange,
                        quantity=h.quantity,
                        average_price=h.average_price,
                        current_price=h.current_price,
                        isin=h.isin,
                        company_name=h.company_name,
                        raw=h.raw,
                    )
                key = (h.isin or h.stock_code, h.exchange_code)
                if key in seen:
                    continue
                seen.add(key)
                holdings.append(h)

        # If we got nothing AND every exchange errored, surface the last error.
        if not holdings and last_error is not None:
            raise BreezeError(str(last_error))

        # Breeze's holdings payload omits ISIN and company name. Fill them in
        # by calling get_names() per stock_code. This is the slow path of the
        # sync but only runs once per session.
        return self._enrich_with_names(holdings)

    def _enrich_with_names(self, holdings: list[BrokerHolding]) -> list[BrokerHolding]:
        enriched: list[BrokerHolding] = []
        for h in holdings:
            if h.exchange_stock_code and h.company_name:
                enriched.append(h)
                continue
            ex_ticker, name = self._lookup_name(h.exchange_code, h.stock_code)
            if not ex_ticker and not name:
                enriched.append(h)
                continue
            enriched.append(BrokerHolding(
                stock_code=h.stock_code,
                exchange_code=h.exchange_code,
                quantity=h.quantity,
                average_price=h.average_price,
                current_price=h.current_price,
                isin=h.isin,
                company_name=name or h.company_name,
                exchange_stock_code=ex_ticker or h.exchange_stock_code,
                raw=h.raw,
            ))
        return enriched

    def get_option_chain(
        self,
        *,
        stock_code: str,
        expiry: date,
        right: Optional[str] = None,
    ) -> list[OptionContract]:
        """Pull the NSE option chain for an underlying + expiry.

        Args:
          stock_code: ICICI broker code for the underlying (e.g. 'NIFTY',
            'BANKNIFTY', 'RELIANCE', 'EXIIND'). NOT the NSE ticker.
          expiry: Python date.
          right: 'call' / 'put' to filter, or None for both.
        """
        expiry_iso = _breeze_expiry(expiry)
        rights = ["call", "put"] if right is None else [right]
        out: list[OptionContract] = []

        for r in rights:
            try:
                resp = self._sdk.get_option_chain_quotes(
                    stock_code=stock_code,
                    exchange_code="NFO",
                    product_type="options",
                    expiry_date=expiry_iso,
                    right=r,
                )
            except Exception as e:
                msg = str(e).lower()
                if "session" in msg or "auth" in msg or "expired" in msg:
                    raise BreezeSessionExpired(str(e)) from e
                raise BreezeError(str(e)) from e

            if not isinstance(resp, dict):
                continue
            err = resp.get("Error") or resp.get("error")
            if err:
                # 'no data for this expiry on the put side' should not fail
                # the whole fetch — skip and continue with the other side.
                msg = str(err).lower()
                if "no" in msg and ("data" in msg or "result" in msg or "record" in msg):
                    continue
                if "session" in msg or "auth" in msg:
                    raise BreezeSessionExpired(str(err))
                raise BreezeError(str(err))

            records = resp.get("Success") or resp.get("success") or []
            if not isinstance(records, list):
                continue
            for rec in records:
                if not isinstance(rec, dict):
                    continue
                try:
                    out.append(_parse_option(rec, default_right=r, default_expiry=expiry.isoformat()))
                except (ValueError, TypeError):
                    continue

        # Sort by strike, calls first then puts at the same strike.
        out.sort(key=lambda c: (c.strike_price, 0 if c.right == "call" else 1))
        return out

    def debug_probe(
        self,
        *,
        stock_code: str,
        candidates: list[date],
    ) -> list[dict]:
        """Diagnostic: return the raw shape of Breeze's response for every
        candidate date, so we can see WHY a given date didn't come through
        the regular probe. Read-only and bounded by the candidate count."""
        out: list[dict] = []
        for d in candidates:
            entry: dict = {"date": d.isoformat(), "weekday": d.strftime("%A")}
            try:
                resp = self._sdk.get_option_chain_quotes(
                    stock_code=stock_code,
                    exchange_code="NFO",
                    product_type="options",
                    expiry_date=_breeze_expiry(d),
                    right="call",
                )
                if not isinstance(resp, dict):
                    entry["shape"] = type(resp).__name__
                    entry["status"] = "non-dict response"
                else:
                    err = resp.get("Error") or resp.get("error")
                    records = resp.get("Success") or resp.get("success") or []
                    entry["error"] = err
                    entry["records_count"] = len(records) if isinstance(records, list) else None
                    entry["status_code"] = resp.get("Status") or resp.get("status")
                    entry["keys"] = sorted(resp.keys())
                    if isinstance(records, list) and records:
                        entry["sample"] = records[0]
                    entry["status"] = "ok" if (isinstance(records, list) and records) else "empty"
            except Exception as e:
                entry["exception"] = f"{type(e).__name__}: {str(e)[:200]}"
                entry["status"] = "exception"
            out.append(entry)
        return out

    def find_available_expiries(
        self,
        *,
        stock_code: str,
        candidates: list[date],
    ) -> list[date]:
        """Probe Breeze for which candidate expiry dates actually have
        contracts for an underlying.

        We try the call side only — calls and puts share the same expiry
        calendar, so probing one side is enough and halves the API cost.
        A date is included in the result if Breeze returns at least one
        contract row for it.

        Raises BreezeSessionExpired on auth errors. Per-date errors are
        swallowed so a single bad probe doesn't kill the whole list.
        """
        out: list[date] = []
        for d in candidates:
            try:
                resp = self._sdk.get_option_chain_quotes(
                    stock_code=stock_code,
                    exchange_code="NFO",
                    product_type="options",
                    expiry_date=_breeze_expiry(d),
                    right="call",
                )
            except Exception as e:
                msg = str(e).lower()
                if "session" in msg or "auth" in msg or "expired" in msg:
                    raise BreezeSessionExpired(str(e)) from e
                continue

            if not isinstance(resp, dict):
                continue
            err = resp.get("Error") or resp.get("error")
            if err:
                msg = str(err).lower()
                if "session" in msg or "auth" in msg:
                    raise BreezeSessionExpired(str(err))
                continue

            records = resp.get("Success") or resp.get("success") or []
            if isinstance(records, list) and len(records) > 0:
                out.append(d)
        return out

    def _lookup_name(self, exchange_code: str, stock_code: str) -> tuple[str, str]:
        """Resolve a Breeze stock_code → (exchange_stock_code, company_name)
        via get_names(). Returns ('', '') if the SDK call fails. Never raises."""
        if not stock_code:
            return "", ""
        broker_exchange = (exchange_code or "NSE").upper()
        try:
            resp = self._sdk.get_names(exchange_code=broker_exchange, stock_code=stock_code)
        except Exception:
            return "", ""
        if not isinstance(resp, dict):
            return "", ""

        ex_ticker = ""
        for k in ("exchange_stock_code", "exchangeStockCode", "exchange_symbol"):
            v = resp.get(k)
            if v:
                ex_ticker = str(v).strip().upper()
                break

        name = ""
        # Yes — the key has a space. Real Breeze response: "company name".
        for k in ("company name", "company_name", "Company Name", "stock_name", "name"):
            v = resp.get(k)
            if v:
                name = str(v).strip()
                break
        return ex_ticker, name


_ISIN_KEYS = ("isin", "ISIN", "isin_code", "stock_ISIN", "stock_isin", "isin_no")
_NAME_KEYS = ("company_name", "stock_name", "name", "company")
_QTY_KEYS = ("quantity", "Qty", "qty", "holding_qty")
_AVG_KEYS = ("average_price", "avg_price", "average_cost", "avgcost", "cost_basis")
_CUR_KEYS = ("current_market_price", "ltp", "last_traded_price", "current_price", "market_price")


def _first(r: dict, keys: tuple[str, ...], default=None):
    for k in keys:
        v = r.get(k)
        if v not in (None, ""):
            return v
    return default


def _parse_holding(r: dict) -> BrokerHolding:
    qty_raw = _first(r, _QTY_KEYS, 0)
    avg_raw = _first(r, _AVG_KEYS, 0)
    cur_raw = _first(r, _CUR_KEYS)
    return BrokerHolding(
        stock_code=str(r.get("stock_code") or r.get("symbol") or "").strip(),
        exchange_code=str(r.get("exchange_code") or r.get("exchange") or "NSE").strip().upper(),
        quantity=float(qty_raw or 0),
        average_price=float(avg_raw or 0),
        current_price=float(cur_raw) if cur_raw not in (None, "") else None,
        isin=str(_first(r, _ISIN_KEYS, "") or "").strip(),
        company_name=_first(r, _NAME_KEYS),
        raw=r,
    )


_BID_KEYS = ("best_bid_price", "bid", "best_bid", "bid_price")
_ASK_KEYS = ("best_offer_price", "ask", "best_ask", "offer", "best_offer", "ask_price")
_LTP_KEYS = ("ltp", "last_price", "last_traded_price", "current_market_price")
_OI_KEYS = ("open_interest", "openInterest", "OI", "oi")
_VOL_KEYS = ("total_quantity_traded", "volume", "ttv", "total_volume_traded")
_STRIKE_KEYS = ("strike_price", "strike", "strikePrice")
_RIGHT_KEYS = ("right", "option_type", "type")


def _coerce_num(v) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _parse_option(r: dict, *, default_right: str, default_expiry: str) -> OptionContract:
    right_raw = (_first(r, _RIGHT_KEYS) or default_right or "").strip().lower()
    if right_raw not in ("call", "put"):
        # Breeze sometimes returns "CE"/"PE"
        if right_raw in ("ce", "c"):
            right_raw = "call"
        elif right_raw in ("pe", "p"):
            right_raw = "put"
        else:
            right_raw = default_right
    return OptionContract(
        stock_code=str(r.get("stock_code") or "").strip(),
        expiry_date=str(r.get("expiry_date") or default_expiry).split("T")[0],
        strike_price=float(_first(r, _STRIKE_KEYS, 0) or 0),
        right=right_raw,
        bid=_coerce_num(_first(r, _BID_KEYS)),
        ask=_coerce_num(_first(r, _ASK_KEYS)),
        ltp=_coerce_num(_first(r, _LTP_KEYS)),
        open_interest=_coerce_num(_first(r, _OI_KEYS)),
        volume=_coerce_num(_first(r, _VOL_KEYS)),
        raw=r,
    )


def _breeze_expiry(d: date) -> str:
    """Breeze wants ISO 8601 with time at 06:00:00.000Z."""
    return f"{d.isoformat()}T06:00:00.000Z"
