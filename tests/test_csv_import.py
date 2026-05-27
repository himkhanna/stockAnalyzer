from datetime import date
from pathlib import Path

import pytest

from portfolio_intel.portfolio.csv_import import (
    import_csv_file,
    parse_portfolio_csv,
)


def test_parses_well_formed_rows():
    rows = [
        {"ticker": "AAPL", "market": "US", "shares": "10", "cost_basis": "180", "date": "2024-01-15"},
        {"ticker": "RELIANCE.NS", "market": "", "shares": "25", "cost_basis": "2450", "date": ""},
        {"ticker": "INFY", "market": "NSE", "shares": "30", "cost_basis": "1500", "date": "2024-07-10"},
    ]
    r = parse_portfolio_csv(rows, today=date(2026, 5, 26))
    assert r.ok
    assert len(r.holdings) == 3

    h = {x.ticker: x for x in r.holdings}
    assert h["AAPL"].market_code == "US" and h["AAPL"].currency == "USD"
    assert h["RELIANCE"].market_code == "NSE" and h["RELIANCE"].currency == "INR"
    assert h["RELIANCE"].date_added == date(2026, 5, 26)  # default to today
    assert h["INFY"].market_code == "NSE"


def test_qualified_suffix_beats_market_column():
    rows = [{"ticker": "RELIANCE.BO", "market": "NSE", "shares": "1", "cost_basis": "100"}]
    r = parse_portfolio_csv(rows)
    assert r.holdings[0].market_code == "BSE"


def test_collects_row_errors_without_aborting():
    rows = [
        {"ticker": "AAPL", "market": "US", "shares": "10", "cost_basis": "180"},
        {"ticker": "", "market": "US", "shares": "1", "cost_basis": "1"},
        {"ticker": "MSFT", "market": "US", "shares": "abc", "cost_basis": "1"},
        {"ticker": "GOOG", "market": "US", "shares": "-1", "cost_basis": "1"},
    ]
    r = parse_portfolio_csv(rows)
    assert len(r.holdings) == 1
    assert len(r.errors) == 3
    assert {e.row_number for e in r.errors} == {3, 4, 5}
    assert not r.ok


def test_handles_thousands_separator_in_numbers():
    rows = [{"ticker": "RELIANCE.NS", "shares": "1,000", "cost_basis": "2,450.50"}]
    r = parse_portfolio_csv(rows)
    assert r.holdings[0].shares == 1000.0
    assert r.holdings[0].cost_basis == 2450.50


def test_missing_market_for_bare_ticker_defaults_to_us():
    """Matches parse_ticker's behaviour: bare symbol with no market = US."""
    rows = [{"ticker": "AAPL", "shares": "1", "cost_basis": "100"}]
    r = parse_portfolio_csv(rows)
    assert r.holdings[0].market_code == "US"


def test_import_file(tmp_path):
    p = tmp_path / "p.csv"
    p.write_text(
        "ticker,market,shares,cost_basis,date\n"
        "AAPL,US,50,182,2024-03-15\n"
        "RELIANCE.NS,,25,2450,2024-06-01\n",
        encoding="utf-8",
    )
    r = import_csv_file(p)
    assert r.ok
    assert len(r.holdings) == 2


def test_import_file_rejects_missing_required_columns(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("ticker,market\nAAPL,US\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing required columns"):
        import_csv_file(p)


def test_import_file_handles_bom(tmp_path):
    """Excel exports with UTF-8 BOM should not break header parsing."""
    p = tmp_path / "bom.csv"
    p.write_bytes(b"\xef\xbb\xbfticker,shares,cost_basis\nAAPL,10,100\n")
    r = import_csv_file(p)
    assert r.ok and len(r.holdings) == 1
