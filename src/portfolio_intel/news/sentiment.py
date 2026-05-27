"""Keyword-based sentiment tally.

Each headline is scored by counting positive and negative trigger words.
- score > 0  -> positive
- score < 0  -> negative
- score == 0 -> neutral

This is intentionally crude. The goal is a stable, explainable count we
can hand to the LLM as a fact ("3 positive, 1 neutral, 1 negative"), not
a state-of-the-art classifier. Anything fancier risks 'the model decided
the news was bullish, so it sounds bullish' — exactly what CLAUDE.md says
to avoid.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from ..data.models import NewsItem


POSITIVE = {
    "beat", "beats", "surge", "surges", "rally", "rallies", "rise", "rises",
    "growth", "grow", "grows", "upgrade", "upgrades", "upgraded",
    "outperform", "outperforms", "bullish", "strong", "record",
    "gain", "gains", "boost", "boosts", "boosted", "raises", "raised",
    "buy", "overweight", "positive", "approval", "approved", "expansion",
    "wins", "won", "partnership", "deal", "exceeds", "exceeded",
    "profit", "profits", "dividend", "buyback",
}
NEGATIVE = {
    "miss", "misses", "missed", "fall", "falls", "fell", "drop", "drops",
    "dropped", "decline", "declines", "declined", "downgrade", "downgrades",
    "downgraded", "underperform", "underperforms", "bearish", "weak", "weakens",
    "loss", "losses", "plunge", "plunges", "cut", "cuts", "warning", "warns",
    "concern", "concerns", "concerning", "lawsuit", "probe", "investigation",
    "fraud", "recall", "delay", "delayed", "layoff", "layoffs", "fired",
    "sell", "underweight", "negative", "rejected", "denies", "denied", "slump",
}

# Coarse themes — counts of triggers per category. Surfaced to the LLM as
# context, not as a 'verdict.'
THEMES = {
    "earnings":   {"earnings", "eps", "revenue", "guidance", "beat", "miss", "quarter"},
    "analyst":    {"upgrade", "downgrade", "target", "rating", "analyst", "coverage"},
    "regulatory": {"sec", "fda", "antitrust", "regulator", "regulatory", "probe", "lawsuit", "fine"},
    "product":    {"launch", "launches", "product", "release", "unveils", "rollout"},
    "deals":      {"acquisition", "acquires", "merger", "partnership", "deal", "buyback", "dividend"},
    "leadership": {"ceo", "cfo", "resigns", "appoints", "fired", "executive"},
}


@dataclass(frozen=True)
class SentimentSummary:
    total: int
    positive: int
    neutral: int
    negative: int
    themes: list[str] = field(default_factory=list)  # most-mentioned theme labels
    sample_titles: list[str] = field(default_factory=list)  # up to a few, for display

    @property
    def label(self) -> str:
        if self.total == 0:
            return "no news"
        if self.positive > self.negative * 2 and self.positive >= 2:
            return "mostly positive"
        if self.negative > self.positive * 2 and self.negative >= 2:
            return "mostly negative"
        if self.positive == 0 and self.negative == 0:
            return "neutral"
        return "mixed"


_TOKEN_RE = re.compile(r"[a-z][a-z'-]*")


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def score_headline(title: str) -> int:
    tokens = set(_tokens(title))
    return len(tokens & POSITIVE) - len(tokens & NEGATIVE)


def tally(items: list[NewsItem], *, sample_n: int = 3) -> SentimentSummary:
    pos = neu = neg = 0
    theme_counts: Counter[str] = Counter()
    for it in items:
        text = f"{it.title} {it.summary or ''}"
        toks = set(_tokens(text))
        s = len(toks & POSITIVE) - len(toks & NEGATIVE)
        if s > 0:
            pos += 1
        elif s < 0:
            neg += 1
        else:
            neu += 1
        for theme, kw in THEMES.items():
            if toks & kw:
                theme_counts[theme] += 1

    top_themes = [t for t, _ in theme_counts.most_common(3)]
    samples = [it.title for it in items[:sample_n]]
    return SentimentSummary(
        total=len(items),
        positive=pos,
        neutral=neu,
        negative=neg,
        themes=top_themes,
        sample_titles=samples,
    )
