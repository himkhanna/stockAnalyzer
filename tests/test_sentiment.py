from datetime import datetime, timezone

from portfolio_intel.data.models import NewsItem
from portfolio_intel.news.sentiment import score_headline, tally


def _ni(title: str, summary: str | None = None) -> NewsItem:
    return NewsItem(
        title=title,
        publisher="x",
        url="",
        published_at=datetime.now(timezone.utc),
        summary=summary,
    )


def test_score_positive_headline():
    assert score_headline("Apple beats earnings and raises guidance") > 0


def test_score_negative_headline():
    assert score_headline("Apple misses earnings; analysts downgrade") < 0


def test_score_neutral_headline():
    assert score_headline("Apple announces conference next week") == 0


def test_tally_mostly_positive():
    items = [
        _ni("Co. beats earnings"),
        _ni("Analysts upgrade to overweight"),
        _ni("Quarterly buyback approved"),
        _ni("Co. holds annual meeting"),
    ]
    s = tally(items)
    assert s.total == 4
    assert s.positive == 3
    assert s.label == "mostly positive"


def test_tally_mostly_negative():
    items = [
        _ni("Co. misses guidance"),
        _ni("Probe into accounting practices widens"),
        _ni("Analysts downgrade; shares plunge"),
    ]
    s = tally(items)
    assert s.negative == 3
    assert s.label == "mostly negative"


def test_tally_mixed():
    items = [_ni("beats earnings"), _ni("faces lawsuit")]
    s = tally(items)
    assert s.label == "mixed"


def test_tally_empty_label():
    s = tally([])
    assert s.label == "no news"
    assert s.total == 0


def test_tally_extracts_themes():
    items = [
        _ni("Co. beats earnings forecast"),
        _ni("Analyst raises target after earnings"),
        _ni("Earnings guidance for next quarter"),
    ]
    s = tally(items)
    assert "earnings" in s.themes
