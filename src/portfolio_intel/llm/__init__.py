"""LLM layer.

Strict separation from the math layer: the model only reasons over data it
is given. It never invents prices, RSI values, or targets. The prompt is
the lever that enforces the honest tone CLAUDE.md mandates.
"""
