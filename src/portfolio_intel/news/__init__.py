"""News + sentiment.

This layer is part of the 'math' tier — sentiment is a deterministic
keyword tally, NOT an LLM judgment. CLAUDE.md is explicit: 'Simple
sentiment tally (positive/neutral/negative counts + themes).' Keeping
sentiment outside the LLM means the model's tone can't bias the count.
"""
