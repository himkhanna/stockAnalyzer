"""Discovery: scan curated per-market universes for high-scoring names
that aren't already in the user's portfolio.

The scoring engine is the same one used everywhere else — this is a
filter and a ranking, not a new signal source. Per CLAUDE.md, every
directional read here is backed by deterministic math + rules.
"""
from .scanner import DiscoveredRow, scan_universe
from .universes import UNIVERSES, universe_for

__all__ = ["DiscoveredRow", "scan_universe", "UNIVERSES", "universe_for"]
