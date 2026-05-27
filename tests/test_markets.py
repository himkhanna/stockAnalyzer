import pytest

from portfolio_intel.markets import Market, parse_ticker


def test_format_ticker_us_is_bare():
    assert Market.US.format_ticker("aapl") == "AAPL"


def test_format_ticker_nse_appends_suffix():
    assert Market.NSE.format_ticker("reliance") == "RELIANCE.NS"


def test_format_ticker_bse_appends_suffix():
    assert Market.BSE.format_ticker("RELIANCE") == "RELIANCE.BO"


def test_format_ticker_idempotent_when_already_qualified():
    assert Market.NSE.format_ticker("RELIANCE.NS") == "RELIANCE.NS"


def test_format_ticker_rejects_empty():
    with pytest.raises(ValueError):
        Market.US.format_ticker("  ")


def test_parse_ticker_qualified_nse():
    symbol, market = parse_ticker("RELIANCE.NS")
    assert symbol == "RELIANCE"
    assert market is Market.NSE


def test_parse_ticker_qualified_bse():
    symbol, market = parse_ticker("reliance.bo")
    assert symbol == "RELIANCE"
    assert market is Market.BSE


def test_parse_ticker_bare_defaults_to_us():
    symbol, market = parse_ticker("AAPL")
    assert symbol == "AAPL"
    assert market is Market.US


def test_parse_ticker_bare_with_explicit_market():
    symbol, market = parse_ticker("INFY", default_market=Market.NSE)
    assert symbol == "INFY"
    assert market is Market.NSE


def test_market_from_code():
    assert Market.from_code("nse") is Market.NSE
    with pytest.raises(ValueError):
        Market.from_code("XYZ")


def test_currency_is_market_native():
    assert Market.US.currency == "USD"
    assert Market.NSE.currency == "INR"
    assert Market.BSE.currency == "INR"
