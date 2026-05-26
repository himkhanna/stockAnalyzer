"""Tests for broker-specific CSV translation.

ICICI Direct's export uses internal short codes (EXIIND, GABIND...) that
aren't NSE tickers, so the importer resolves via ISIN. Yahoo Search is
stubbed in these tests so they run offline.
"""
from __future__ import annotations

from pathlib import Path

from portfolio_intel.portfolio.brokers import (
    detect_broker,
    translate,
    ICICI_DIRECT_HEADERS,
)
from portfolio_intel.portfolio.ticker_resolver import Resolution, TickerResolver


class _FakeResolver(TickerResolver):
    """Resolver stub: resolves anything whose ISIN starts with 'INE' to a
    deterministic NSE symbol; returns None for everything else."""

    def __init__(self, fail_isins: set[str] | None = None) -> None:
        self._fail = fail_isins or set()

    def resolve(self, *, isin="", name="", fallback=""):
        if isin in self._fail:
            return None
        if isin.startswith("INE"):
            return Resolution(
                bare_symbol=f"NSE_{isin[-4:]}",
                qualified=f"NSE_{isin[-4:]}.NS",
                source="cache",
                confidence="high",
            )
        return None


# ---------------- Detection ----------------

def test_detect_icici_direct_header_signature():
    headers = [
        "Stock Symbol", "Company Name", "ISIN Code", "Qty",
        "Average Cost Price", "Current Market Price",
    ]
    assert detect_broker(headers) == "icici_direct"


def test_detect_canonical_format_returns_none():
    headers = ["ticker", "market", "shares", "cost_basis", "date"]
    assert detect_broker(headers) is None


def test_detect_handles_case_insensitive_headers():
    headers = ["STOCK SYMBOL", "company name", "ISIN code", "qty", "average cost price"]
    assert detect_broker(headers) == "icici_direct"


def test_detect_empty_headers():
    assert detect_broker([]) is None
    assert detect_broker(["", "  "]) is None


# ---------------- Translation ----------------

def _icici_row(symbol, name, isin, qty, avg):
    return {
        "Stock Symbol": symbol,
        "Company Name": name,
        "ISIN Code": isin,
        "Qty": qty,
        "Average Cost Price": avg,
        # plus other columns the parser ignores
        "Realized Profit / Loss": "0.00",
    }


def test_translate_canonical_rows_are_qualified_nse_tickers():
    rows = [
        _icici_row("EXIIND", "EXIDE INDUSTRIES LTD", "INE302A01020", "100", "198.63"),
        _icici_row("TCS", "TATA CONSULTANCY SERVICES LTD", "INE467B01029", "140", "2841.63"),
    ]
    t = translate("icici_direct", rows, resolver=_FakeResolver())
    assert len(t.canonical_rows) == 2
    assert all(r["ticker"].endswith(".NS") for r in t.canonical_rows)
    assert all(r["market"] == "NSE" for r in t.canonical_rows)
    # shares + cost flow through unchanged for the canonical parser to coerce
    assert t.canonical_rows[0]["shares"] == "100"
    assert t.canonical_rows[0]["cost_basis"] == "198.63"


def test_translate_collects_unresolved_rows_without_dropping_resolved_ones():
    rows = [
        _icici_row("EXIIND", "EXIDE INDUSTRIES LTD", "INE302A01020", "100", "198.63"),
        _icici_row("WEIRD", "OBSCURE LTD", "INE000NOPE9", "10", "50.00"),
        _icici_row("TCS", "TATA CONSULTANCY SERVICES LTD", "INE467B01029", "140", "2841.63"),
    ]
    resolver = _FakeResolver(fail_isins={"INE000NOPE9"})
    t = translate("icici_direct", rows, resolver=resolver)
    assert len(t.canonical_rows) == 2
    assert len(t.unresolved) == 1
    assert t.unresolved[0]["isin"] == "INE000NOPE9"
    assert "could not resolve" in t.unresolved[0]["reason"].lower()


def test_translate_skips_blank_rows():
    rows = [
        _icici_row("EXIIND", "EXIDE INDUSTRIES LTD", "INE302A01020", "100", "198.63"),
        {k: "" for k in ICICI_DIRECT_HEADERS},  # all blanks, mimics trailing CSV line
    ]
    t = translate("icici_direct", rows, resolver=_FakeResolver())
    assert len(t.canonical_rows) == 1
    assert len(t.unresolved) == 0


def test_translate_progress_callback_fires_per_row():
    rows = [
        _icici_row("EXIIND", "EXIDE INDUSTRIES LTD", "INE302A01020", "100", "198.63"),
        _icici_row("TCS", "TCS LTD", "INE467B01029", "10", "2800"),
    ]
    seen: list[tuple[int, int, str, str | None]] = []
    translate(
        "icici_direct", rows, resolver=_FakeResolver(),
        on_progress=lambda i, total, key, resolved: seen.append((i, total, key, resolved)),
    )
    assert len(seen) == 2
    assert seen[0][:2] == (1, 2)
    assert seen[0][2] == "EXIIND"
    assert seen[0][3] is not None and seen[0][3].endswith(".NS")


# ---------------- Resolver cache behavior ----------------

def test_resolver_uses_override_file_first(tmp_path):
    override_file = tmp_path / "overrides.json"
    override_file.write_text('{"INE302A01020": "EXIDEIND"}', encoding="utf-8")
    r = TickerResolver(
        cache_path=tmp_path / "cache.json",
        overrides_path=override_file,
    )
    res = r.resolve(isin="INE302A01020", name="EXIDE INDUSTRIES LTD")
    assert res is not None
    assert res.bare_symbol == "EXIDEIND"
    assert res.source == "override"
    assert res.confidence == "high"


def test_resolver_caches_misses(tmp_path):
    """A failed lookup should be cached as empty so we don't re-hit Yahoo."""
    r = TickerResolver(
        cache_path=tmp_path / "cache.json",
        overrides_path=tmp_path / "overrides.json",
    )

    # Force yahoo lookups to fail (no yfinance access in tests anyway).
    r._yahoo_search = lambda q: None

    # First call: tries Yahoo, fails, caches the miss.
    res1 = r.resolve(isin="INE999XYZ999", name="Nonexistent")
    assert res1 is None
    # Second call: should return None from cache without re-trying.
    r._yahoo_search = lambda q: (_ for _ in ()).throw(AssertionError("should not be called"))
    res2 = r.resolve(isin="INE999XYZ999", name="Nonexistent")
    assert res2 is None
