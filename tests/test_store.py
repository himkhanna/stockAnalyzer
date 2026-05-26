from datetime import date

import pytest

from portfolio_intel.portfolio.models import Holding
from portfolio_intel.portfolio.store import PortfolioStore


@pytest.fixture
def store(tmp_path):
    return PortfolioStore(tmp_path / "test.db")


def _h(ticker="AAPL", market="US", shares=10, cost=180.0, ccy="USD"):
    return Holding(
        ticker=ticker,
        market_code=market,
        shares=shares,
        cost_basis=cost,
        currency=ccy,
        date_added=date(2025, 1, 15),
    )


def test_upsert_and_get(store):
    store.upsert(_h())
    got = store.get("AAPL", "US")
    assert got is not None
    assert got.shares == 10
    assert got.cost_basis == 180.0
    assert got.currency == "USD"


def test_upsert_updates_existing(store):
    store.upsert(_h(shares=10, cost=180))
    store.upsert(_h(shares=15, cost=190))
    got = store.get("AAPL", "US")
    assert got.shares == 15
    assert got.cost_basis == 190


def test_same_ticker_different_markets_coexist(store):
    """A US AAPL and a hypothetical AAPL.NS would be distinct rows."""
    store.upsert(_h(ticker="RELIANCE", market="NSE", ccy="INR"))
    store.upsert(_h(ticker="RELIANCE", market="BSE", ccy="INR"))
    assert len(store.all()) == 2


def test_remove(store):
    store.upsert(_h())
    assert store.remove("AAPL", "US") is True
    assert store.remove("AAPL", "US") is False
    assert store.get("AAPL", "US") is None


def test_all_empty(store):
    assert store.all() == []


def test_cost_basis_currency_preserved(store):
    """Currency comes from the position; the store does no FX conversion."""
    store.upsert(_h(ticker="RELIANCE", market="NSE", cost=2500, ccy="INR"))
    store.upsert(_h(ticker="AAPL", market="US", cost=180, ccy="USD"))
    holdings = {h.ticker: h for h in store.all()}
    assert holdings["RELIANCE"].currency == "INR"
    assert holdings["AAPL"].currency == "USD"


def test_ticker_normalized_to_upper(store):
    store.upsert(_h(ticker="aapl"))
    assert store.get("aapl", "us") is not None
    assert store.get("AAPL", "US") is not None
