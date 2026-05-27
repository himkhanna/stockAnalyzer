"""Options module: Black-Scholes pricing, NSE expiry calendar, chain types.

Pure math + small helpers. The broker-specific chain fetcher lives in
brokers/icici_breeze.py to keep the SDK dependency isolated.
"""
from .expiries import (
    candidate_expiries,
    last_thursday_of_month,
    next_monthly_expiries,
    next_weekly_expiries,
)
from .pricing import (
    DEFAULT_DIVIDEND_YIELD,
    DEFAULT_RISK_FREE_IN,
    Greeks,
    bs_greeks,
    bs_price,
    implied_vol,
    years_to_expiry,
)
from .stats import iv_rv_label, realized_volatility

__all__ = [
    "DEFAULT_DIVIDEND_YIELD",
    "DEFAULT_RISK_FREE_IN",
    "Greeks",
    "bs_greeks",
    "bs_price",
    "implied_vol",
    "years_to_expiry",
    "candidate_expiries",
    "iv_rv_label",
    "last_thursday_of_month",
    "next_monthly_expiries",
    "next_weekly_expiries",
    "realized_volatility",
]
