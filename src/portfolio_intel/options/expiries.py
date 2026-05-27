"""NSE F&O expiry calendar.

Monthly stock-option expiries fall on the last Thursday of each month
(or the previous trading day if Thursday is a holiday — that's a separate
concern; we don't try to load NSE's full holiday calendar here).

Weekly NIFTY / BANKNIFTY / FINNIFTY expiries are also on Thursdays.

Used for the expiry dropdown in the chain viewer. Date math only —
no broker calls.
"""
from __future__ import annotations

from datetime import date, timedelta


def last_thursday_of_month(year: int, month: int) -> date:
    # Find the last day of the month, then walk back to Thursday (weekday() == 3).
    if month == 12:
        first_next = date(year + 1, 1, 1)
    else:
        first_next = date(year, month + 1, 1)
    last_day = first_next - timedelta(days=1)
    offset = (last_day.weekday() - 3) % 7
    return last_day - timedelta(days=offset)


def next_monthly_expiries(count: int = 6, ref: date | None = None) -> list[date]:
    ref = ref or date.today()
    out: list[date] = []
    y, m = ref.year, ref.month
    while len(out) < count:
        d = last_thursday_of_month(y, m)
        if d >= ref:
            out.append(d)
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out


def next_weekly_expiries(count: int = 8, ref: date | None = None) -> list[date]:
    """Every Thursday from today. Index options use these."""
    ref = ref or date.today()
    days_to_thu = (3 - ref.weekday()) % 7
    if days_to_thu == 0 and ref.weekday() == 3:
        first = ref
    else:
        first = ref + timedelta(days=days_to_thu or 7)
    return [first + timedelta(days=7 * i) for i in range(count)]


def candidate_expiries(months: int = 3, ref: date | None = None) -> list[date]:
    """Plausible monthly expiry dates to probe for an underlying.

    NSE has shifted several products' expiry day-of-week over recent SEBI
    cycles (the historic last-Thursday rule, last-Tuesday for current
    stock-option monthlies after the 2025 shift). Brokers also sometimes
    surface the settlement date a day or two after expiry. Rather than
    encode the full ruleset, we generate the LAST OCCURRENCE of each
    weekday (Mon-Fri) within the month for `months` upcoming cycles and
    let Breeze tell us which ones actually have contracts.

    Critically the last-Tuesday of a month can fall AFTER the last
    Thursday (e.g. June 2026: last Thu = Jun 25, last Tue = Jun 30),
    so we must search the entire month, not just the week containing
    the last Thursday.

    Returns sorted unique dates >= ref.
    """
    ref = ref or date.today()
    out: set[date] = set()
    y, m = ref.year, ref.month
    for _ in range(months):
        if m == 12:
            first_next = date(y + 1, 1, 1)
        else:
            first_next = date(y, m + 1, 1)
        last_day = first_next - timedelta(days=1)
        # For each weekday Mon (0) through Fri (4), find the last
        # occurrence in the month by walking back from last_day.
        for target_wd in range(0, 5):
            d = last_day
            while d.weekday() != target_wd:
                d -= timedelta(days=1)
            if d >= ref:
                out.add(d)
        m += 1
        if m > 12:
            m = 1
            y += 1
    return sorted(out)
