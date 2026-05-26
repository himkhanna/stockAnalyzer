"""Broker integrations (read-only).

This package wraps third-party broker APIs behind small, testable
interfaces. It is deliberately read-only — no order placement code lives
here. Per CLAUDE.md, this tool is decision support; trades stay in the
broker's own UI.
"""
from .icici_breeze import (
    BreezeClient,
    BreezeError,
    BreezeNotInstalled,
    BreezeNotConnected,
    BreezeSessionExpired,
    BrokerHolding,
)

__all__ = [
    "BreezeClient",
    "BreezeError",
    "BreezeNotInstalled",
    "BreezeNotConnected",
    "BreezeSessionExpired",
    "BrokerHolding",
]
