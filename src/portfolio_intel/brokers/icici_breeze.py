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

import urllib.parse
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Optional


class BreezeError(Exception):
    """Generic Breeze problem."""


class BreezeNotInstalled(BreezeError):
    """breeze-connect isn't installed. Install with: pip install -e '.[brokers]'"""


class BreezeNotConnected(BreezeError):
    """No active session — credentials missing or session token never generated."""


class BreezeSessionExpired(BreezeError):
    """Session expired (Breeze sessions die at midnight IST). Reconnect."""


@dataclass(frozen=True)
class BrokerHolding:
    """A holding as the broker reports it, before we translate into our canonical schema."""
    stock_code: str          # broker-internal code (often the NSE ticker but not always)
    exchange_code: str       # "NSE" or "BSE"
    quantity: float
    average_price: float
    current_price: Optional[float]
    isin: str
    company_name: Optional[str] = None
    raw: dict | None = None  # original record for debugging


# IST = UTC+05:30
_IST = timezone(timedelta(hours=5, minutes=30))


def login_url(api_key: str) -> str:
    """The URL the user opens in their browser to start the OAuth flow."""
    return f"https://api.icicidirect.com/apiuser/login?api_key={urllib.parse.quote_plus(api_key)}"


def next_session_expiry(now: Optional[datetime] = None) -> datetime:
    """Breeze sessions die at midnight IST. Return the expiry timestamp (UTC)."""
    now = now or datetime.now(tz=timezone.utc)
    now_ist = now.astimezone(_IST)
    expiry_ist = datetime.combine(now_ist.date() + timedelta(days=1), time.min, tzinfo=_IST)
    return expiry_ist.astimezone(timezone.utc)


class BreezeClient:
    """Thin wrapper around breeze_connect.BreezeConnect.

    Created in two phases so we can persist intermediate state:
    - `BreezeClient(api_key)` instantiates the SDK
    - `client.connect(api_secret, session_token)` authenticates
    """

    def __init__(self, api_key: str) -> None:
        try:
            from breeze_connect import BreezeConnect  # type: ignore
        except ImportError as e:
            raise BreezeNotInstalled(
                "breeze-connect is not installed. Run: pip install -e '.[brokers]'"
            ) from e
        self.api_key = api_key
        self._sdk = BreezeConnect(api_key=api_key)

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
        return holdings


def _parse_holding(r: dict) -> BrokerHolding:
    qty_raw = r.get("quantity") or r.get("Qty") or 0
    avg_raw = r.get("average_price") or r.get("avg_price") or 0
    cur_raw = r.get("current_market_price") or r.get("ltp")
    return BrokerHolding(
        stock_code=str(r.get("stock_code") or r.get("symbol") or "").strip(),
        exchange_code=str(r.get("exchange_code") or r.get("exchange") or "NSE").strip().upper(),
        quantity=float(qty_raw or 0),
        average_price=float(avg_raw or 0),
        current_price=float(cur_raw) if cur_raw not in (None, "") else None,
        isin=str(r.get("isin") or r.get("isin_code") or "").strip(),
        company_name=(r.get("company_name") or r.get("stock_name") or None),
        raw=r,
    )
