"""Discovery: scan curated per-market universes for high-scoring names
that aren't already in the user's portfolio.

The scoring engine is the same one used everywhere else — this is a
filter and a ranking, not a new signal source. Per CLAUDE.md, every
directional read here is backed by deterministic math + rules.
"""
from .diversification import (
    AssetSlice,
    Diversification,
    Instrument,
    classify,
    instruments_for,
    summarise,
)
from .scanner import DiscoveredRow, scan_universe
from .universes import UNIVERSES, sector_for, universe_for

__all__ = [
    "AssetSlice",
    "Diversification",
    "DiscoveredRow",
    "Instrument",
    "UNIVERSES",
    "classify",
    "instruments_for",
    "scan_universe",
    "sector_for",
    "summarise",
    "universe_for",
]
