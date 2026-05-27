"""Tax-loss harvesting helpers.

For each unrealised loss, estimates the tax saving you'd capture by
realising it now. Information only — actual tax treatment depends on
your filing situation, broker reporting, and (in the US) wash-sale
rules we don't track. Use this to surface candidates; verify with your
CA / accountant before acting.

Defaults reflect publicly-stated rates (India equity: STCG 15%,
LTCG 12.5% above the ₹1.25L exempt; US: STCG 22% income-bracket proxy,
LTCG 15%). Rates are wired through as arguments so they can be
overridden.

NOTE on holding period for Indian equity: STCG applies to <= 12 months
holding; LTCG to > 12 months. US equity uses the same 1-year boundary
for ST vs LT. Crypto / debt / unlisted have different rules — we cover
only listed equity here.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable, Literal, Optional

TermBucket = Literal["short", "long"]


@dataclass(frozen=True)
class TaxRates:
    short_term: float
    long_term: float
    name: str = ""


# Reasonable defaults. Override per-call when the user supplies their own.
RATES_INDIA = TaxRates(short_term=0.15, long_term=0.125, name="India equity")
RATES_US = TaxRates(short_term=0.22, long_term=0.15, name="US equity (default brackets)")
RATES_DEFAULT = TaxRates(short_term=0.20, long_term=0.15, name="Generic")


def rates_for(market_code: str) -> TaxRates:
    if market_code in ("NSE", "BSE"):
        return RATES_INDIA
    if market_code == "US":
        return RATES_US
    return RATES_DEFAULT


def term_bucket(date_added: date, today: Optional[date] = None) -> TermBucket:
    today = today or date.today()
    days = (today - date_added).days
    # Indian + US equity both use 12-months as the LT boundary for listed shares.
    return "long" if days > 365 else "short"


@dataclass
class HarvestCandidate:
    ticker: str
    market: str
    currency_symbol: str
    shares: float
    cost_basis: float
    price: float
    unrealised_loss: float       # negative number (a loss)
    loss_pct: float              # negative pct
    days_held: int
    term: TermBucket
    tax_rate: float              # the bucket's rate
    est_tax_saving: float        # positive: |loss| * tax_rate
    notes: list[str]


def current_fy(market_code: str, today: Optional[date] = None) -> str:
    """Return the financial-year string for a market.

    India equity: 'YYYY-YY' starting April 1.
    US equity: 'YYYY' (calendar year).
    """
    today = today or date.today()
    if market_code in ("NSE", "BSE"):
        if today.month >= 4:
            return f"{today.year}-{(today.year + 1) % 100:02d}"
        return f"{today.year - 1}-{today.year % 100:02d}"
    return str(today.year)


@dataclass
class FYBucket:
    """Realized-gain totals for one (currency, term) bucket within an FY."""
    currency: str
    currency_symbol: str
    term: str                       # "short" | "long"
    realized_gain: float            # sum (can be negative if losses)
    realized_loss: float            # absolute value of negative entries
    net: float                      # gain + loss (i.e. signed sum)
    n_entries: int
    tax_rate: float
    est_tax_due: float              # before harvest offset and exemption
    ltcg_exempt_applied: float = 0.0  # India only: ₹1.25L exempted from LTCG
    est_tax_due_after_exempt: float = 0.0


def summarise_realized_gains(
    entries: Iterable[dict],
    *,
    currency_symbols: Optional[dict[str, str]] = None,
    ltcg_exempt_inr: float = 125_000.0,
) -> list[FYBucket]:
    """Aggregate realized-gain records into (currency, term) buckets with
    estimated tax due.

    Each entry must have: currency, term, gain_amount.
    Indian LTCG exemption of ₹1.25L is applied per FY per currency=INR
    bucket (term=long). All other buckets get the bucket's bare rate.
    """
    currency_symbols = currency_symbols or {}
    # Index by (currency, term) → running aggregates.
    agg: dict[tuple[str, str], dict] = {}
    for e in entries:
        cur = (e.get("currency") or "").upper()
        term = (e.get("term") or "").lower()
        amt = float(e.get("gain_amount") or 0.0)
        if term not in ("short", "long"):
            continue
        slot = agg.setdefault((cur, term), {
            "realized_gain": 0.0, "realized_loss": 0.0,
            "net": 0.0, "n_entries": 0,
        })
        if amt >= 0:
            slot["realized_gain"] += amt
        else:
            slot["realized_loss"] += abs(amt)
        slot["net"] += amt
        slot["n_entries"] += 1

    out: list[FYBucket] = []
    for (cur, term), v in sorted(agg.items()):
        if cur == "INR":
            rate = RATES_INDIA.short_term if term == "short" else RATES_INDIA.long_term
        elif cur == "USD":
            rate = RATES_US.short_term if term == "short" else RATES_US.long_term
        else:
            rate = RATES_DEFAULT.short_term if term == "short" else RATES_DEFAULT.long_term

        net = v["net"]
        # Tax only on positive net (losses don't generate tax owed; they
        # offset gains in the harvest panel).
        taxable = max(0.0, net)
        est_due = taxable * rate

        # India LTCG: first ₹1.25L of LT capital gains is exempt.
        exempt_applied = 0.0
        if cur == "INR" and term == "long" and taxable > 0:
            exempt_applied = min(taxable, ltcg_exempt_inr)
            est_due_after = max(0.0, taxable - ltcg_exempt_inr) * rate
        else:
            est_due_after = est_due

        out.append(FYBucket(
            currency=cur,
            currency_symbol=currency_symbols.get(cur, cur),
            term=term,
            realized_gain=v["realized_gain"],
            realized_loss=v["realized_loss"],
            net=net,
            n_entries=v["n_entries"],
            tax_rate=rate,
            est_tax_due=est_due,
            ltcg_exempt_applied=exempt_applied,
            est_tax_due_after_exempt=est_due_after,
        ))
    return out


def find_harvest_candidates(
    rows: Iterable[tuple],            # (Holding, market_value, price)
    *,
    today: Optional[date] = None,
    min_loss_pct: float = 1.0,        # ignore noise positions
    min_loss_abs: float = 100.0,      # ignore trivial currency amounts
    currency_symbols: Optional[dict[str, str]] = None,
) -> list[HarvestCandidate]:
    """Build the list of holdings currently in the red, with an estimate
    of the tax saving capturing each loss would yield.

    `rows` is an iterable of (Holding, market_value, price) — caller's
    job to compute market_value from current price (we let the data
    layer do that since it owns yfinance).
    """
    today = today or date.today()
    out: list[HarvestCandidate] = []
    currency_symbols = currency_symbols or {}

    for holding, market_value, price in rows:
        if not holding or holding.shares <= 0 or holding.cost_basis is None:
            continue
        cost_total = holding.cost_basis * holding.shares
        if cost_total <= 0:
            continue
        loss = market_value - cost_total
        if loss >= 0:
            continue
        loss_pct = (loss / cost_total) * 100.0
        if abs(loss_pct) < min_loss_pct or abs(loss) < min_loss_abs:
            continue

        bucket = term_bucket(holding.date_added, today)
        rates = rates_for(holding.market_code)
        rate = rates.short_term if bucket == "short" else rates.long_term
        saving = abs(loss) * rate

        notes: list[str] = []
        if bucket == "short" and holding.market_code in ("NSE", "BSE"):
            days_to_lt = 365 - (today - holding.date_added).days
            if 0 < days_to_lt <= 60:
                notes.append(
                    f"Only {days_to_lt}d until LTCG kicks in — waiting may "
                    "swap the 15% rate for 12.5%."
                )
        if holding.market_code == "US":
            notes.append(
                "Mind the US 30-day wash-sale rule if you plan to re-buy."
            )
        if holding.market_code in ("NSE", "BSE"):
            notes.append(
                "India: LTCG above ₹1.25L per year is taxed at 12.5%; the "
                "estimate assumes you're above the exempt amount."
            )

        out.append(HarvestCandidate(
            ticker=holding.ticker,
            market=holding.market_code,
            currency_symbol=currency_symbols.get(holding.currency, holding.currency),
            shares=holding.shares,
            cost_basis=holding.cost_basis,
            price=price,
            unrealised_loss=loss,
            loss_pct=loss_pct,
            days_held=(today - holding.date_added).days,
            term=bucket,
            tax_rate=rate,
            est_tax_saving=saving,
            notes=notes,
        ))

    # Largest tax saving first.
    out.sort(key=lambda c: c.est_tax_saving, reverse=True)
    return out
