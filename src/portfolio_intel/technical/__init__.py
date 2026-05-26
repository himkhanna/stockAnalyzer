"""Technical-analysis layer.

This layer consumes a price DataFrame and produces deterministic indicator
values. It does NOT call the data API and it does NOT make directional
judgments — those happen in the scoring engine (Phase 4) and LLM synthesis
(Phase 3), respectively. The boundary is enforced by import direction:
nothing in this package may import from `portfolio_intel.data`.
"""
