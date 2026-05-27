"""Asset-class classification and a curated reference of common
diversification instruments per market.

This is information, not advice. We:
  - Classify the user's current holdings into broad asset buckets
    (Equity / ETF / REIT / Gold / Debt / Cash) by symbol heuristics
  - Show which buckets are empty or thin
  - Surface widely-traded instruments per bucket, per market, so the
    user has a starting point to research — never a "buy this" call

The instrument list is intentionally small and well-known. Picking the
right diversification mix is the user's call; we just show them what
exists.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal, Optional

from ..markets import Market

AssetClass = Literal["equity", "etf", "reit", "gold", "debt", "cash", "other"]


@dataclass(frozen=True)
class Instrument:
    symbol: str
    market: str
    name: str
    asset_class: AssetClass
    description: str


# --- Classification heuristics ---

# Symbols that are clearly non-equity in the curated India/US universes.
# Keep the list small — false positives are worse than missing a few.
_EXACT_CLASSIFICATIONS: dict[tuple[str, str], AssetClass] = {
    # India gold / debt / REIT ETFs
    ("GOLDBEES", "NSE"): "gold",
    ("SETFGOLD", "NSE"): "gold",
    ("LIQUIDBEES", "NSE"): "cash",
    ("NIFTYBEES", "NSE"): "etf",
    ("BANKBEES", "NSE"): "etf",
    ("JUNIORBEES", "NSE"): "etf",
    ("BHARAT22ETF", "NSE"): "etf",
    ("CPSEETF", "NSE"): "etf",
    ("EMBASSY", "NSE"): "reit",
    ("MINDSPACE", "NSE"): "reit",
    ("BROOKFIELD", "NSE"): "reit",
    ("NEXUS", "NSE"): "reit",
    # India debt ETFs and bond funds (Bharat Bond)
    ("EBBETF0425", "NSE"): "debt",
    ("EBBETF0430", "NSE"): "debt",
    ("EBBETF0431", "NSE"): "debt",
    ("BBNPPGOLD", "NSE"): "gold",
    # US ETFs
    ("GLD", "US"): "gold",
    ("IAU", "US"): "gold",
    ("SGOL", "US"): "gold",
    ("TLT", "US"): "debt",
    ("AGG", "US"): "debt",
    ("BND", "US"): "debt",
    ("LQD", "US"): "debt",
    ("HYG", "US"): "debt",
    ("VNQ", "US"): "reit",
    ("SCHH", "US"): "reit",
    ("SPY", "US"): "etf",
    ("VOO", "US"): "etf",
    ("VTI", "US"): "etf",
    ("QQQ", "US"): "etf",
    ("BIL", "US"): "cash",
    ("SHV", "US"): "cash",
}


def classify(symbol: str, market_code: str) -> AssetClass:
    """Heuristic asset-class classification by symbol.

    Conservative: anything we can't confidently bucket falls into
    'equity', which is the right default for a stock-tracker portfolio.
    """
    key = (symbol.upper(), market_code.upper())
    if key in _EXACT_CLASSIFICATIONS:
        return _EXACT_CLASSIFICATIONS[key]
    s = symbol.upper()
    if s.endswith("BEES"):
        return "etf"
    if s.endswith("ETF"):
        return "etf"
    return "equity"


# --- Reference instruments per (asset_class, market) ---
# Small, well-known list. The user takes this as a starting point to
# research, not a recommendation. Each entry has a one-line description
# of what the instrument actually is, so the user knows what they're
# looking at before pulling up its chart.

_REFERENCE: list[Instrument] = [
    # India — Gold
    Instrument("GOLDBEES", "NSE", "Nippon India ETF Gold BeES", "gold",
               "Tracks domestic gold price; most-liquid Indian gold ETF."),
    Instrument("SETFGOLD", "NSE", "SBI Gold ETF", "gold",
               "SBI-managed gold ETF tracking domestic gold."),
    # India — Debt
    Instrument("LIQUIDBEES", "NSE", "Nippon Liquid BeES", "cash",
               "Overnight money-market ETF; lowest-risk parking for INR cash."),
    Instrument("EBBETF0432", "NSE", "Bharat Bond ETF (2032)", "debt",
               "Target-maturity ETF of AAA PSU bonds; held to 2032 gives ~7% yield."),
    Instrument("EBBETF0430", "NSE", "Bharat Bond ETF (2030)", "debt",
               "Same as above, 2030 target maturity. Shorter duration = less rate risk."),
    # India — REITs
    Instrument("EMBASSY", "NSE", "Embassy Office Parks REIT", "reit",
               "Largest Indian REIT by AUM; commercial office portfolio."),
    Instrument("MINDSPACE", "NSE", "Mindspace Business Parks REIT", "reit",
               "Office REIT; lower leverage than Embassy."),
    Instrument("BROOKFIELD", "NSE", "Brookfield India REIT", "reit",
               "Office REIT; gateway-city focus."),
    Instrument("NEXUS", "NSE", "Nexus Select Trust", "reit",
               "Retail REIT; mall portfolio across India."),
    # India — Broad equity ETFs (for cost-efficient core)
    Instrument("NIFTYBEES", "NSE", "Nippon India ETF Nifty 50 BeES", "etf",
               "Most-liquid Nifty 50 index ETF; one-instrument equity core."),
    Instrument("JUNIORBEES", "NSE", "Nippon India ETF Nifty Next 50", "etf",
               "Next-50-after-Nifty 50; mid-cap tilt within large-caps."),
    # US — Gold
    Instrument("GLD", "US", "SPDR Gold Shares", "gold",
               "Largest gold ETF globally; physically-backed."),
    Instrument("IAU", "US", "iShares Gold Trust", "gold",
               "Lower expense ratio than GLD; same exposure."),
    # US — Debt
    Instrument("AGG", "US", "iShares Core US Aggregate Bond ETF", "debt",
               "Broad investment-grade US bond market; core debt allocation."),
    Instrument("TLT", "US", "iShares 20+ Year Treasury Bond", "debt",
               "Long-duration US Treasuries; high rate sensitivity (hedge for equity)."),
    Instrument("BIL", "US", "SPDR 1-3 Month T-Bill ETF", "cash",
               "Near-zero-duration T-bills; USD cash equivalent."),
    # US — REITs
    Instrument("VNQ", "US", "Vanguard Real Estate ETF", "reit",
               "Broad US REIT index; one-instrument property exposure."),
    # US — Broad equity
    Instrument("VTI", "US", "Vanguard Total US Stock Market", "etf",
               "Entire US equity market in one ETF; the textbook core holding."),
    Instrument("VOO", "US", "Vanguard S&P 500 ETF", "etf",
               "S&P 500 tracker; lower expense ratio than SPY."),
]


def instruments_for(asset_class: AssetClass, market: Optional[Market] = None) -> list[Instrument]:
    """Return reference instruments for an asset class, optionally
    filtered to a specific market."""
    out = [i for i in _REFERENCE if i.asset_class == asset_class]
    if market is not None:
        out = [i for i in out if i.market == market.code]
    return out


def all_reference() -> list[Instrument]:
    return list(_REFERENCE)


# --- Allocation summary ---

@dataclass
class AssetSlice:
    asset_class: AssetClass
    market_value: float
    pct: float
    n_positions: int


@dataclass
class Diversification:
    by_asset: list[AssetSlice]
    total_value: float
    gaps: list[AssetClass]               # buckets with 0% or < 2% allocation
    suggestions: dict[AssetClass, list[Instrument]]   # gap -> reference list


def summarise(holdings_with_value: Iterable[tuple[str, str, float, int]]) -> Diversification:
    """Build a Diversification summary from (symbol, market, market_value,
    n_positions) tuples. n_positions is 1 per holding; the caller can
    pre-aggregate per asset class if it wants but per-holding is fine."""
    totals: dict[AssetClass, float] = {}
    counts: dict[AssetClass, int] = {}
    grand = 0.0
    for symbol, market_code, mv, _n in holdings_with_value:
        cls = classify(symbol, market_code)
        totals[cls] = totals.get(cls, 0.0) + max(mv, 0.0)
        counts[cls] = counts.get(cls, 0) + 1
        grand += max(mv, 0.0)

    slices: list[AssetSlice] = []
    for cls in ("equity", "etf", "reit", "gold", "debt", "cash", "other"):
        mv = totals.get(cls, 0.0)
        pct = (mv / grand * 100.0) if grand > 0 else 0.0
        slices.append(AssetSlice(
            asset_class=cls,  # type: ignore[arg-type]
            market_value=mv,
            pct=pct,
            n_positions=counts.get(cls, 0),
        ))

    # "Gap" = thin or empty in classes that diversified investors typically
    # hold for portfolio stability.
    diversifiers: list[AssetClass] = ["debt", "gold", "reit"]
    gaps = [s.asset_class for s in slices if s.asset_class in diversifiers and s.pct < 2.0]

    suggestions = {g: instruments_for(g) for g in gaps}

    return Diversification(
        by_asset=slices,
        total_value=grand,
        gaps=gaps,
        suggestions=suggestions,
    )
