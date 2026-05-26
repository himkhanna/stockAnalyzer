"""SQLite portfolio store.

Schema matches CLAUDE.md exactly: ticker, market, shares, cost_basis,
currency, date_added. Cost basis is stored in the currency it was bought in;
the store does no FX conversion.
"""
from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path
from typing import Iterable, Optional

from .models import Holding

_SCHEMA = """
CREATE TABLE IF NOT EXISTS holdings (
    ticker      TEXT NOT NULL,
    market      TEXT NOT NULL,
    shares      REAL NOT NULL,
    cost_basis  REAL NOT NULL,
    currency    TEXT NOT NULL,
    date_added  TEXT NOT NULL,
    PRIMARY KEY (ticker, market)
);
"""


class PortfolioStore:
    def __init__(self, db_path: str | Path = "portfolio.db") -> None:
        self.db_path = str(db_path)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def upsert(self, holding: Holding) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO holdings (ticker, market, shares, cost_basis, currency, date_added)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(ticker, market) DO UPDATE SET
                    shares     = excluded.shares,
                    cost_basis = excluded.cost_basis,
                    currency   = excluded.currency,
                    date_added = excluded.date_added
                """,
                (
                    holding.ticker.upper(),
                    holding.market_code.upper(),
                    float(holding.shares),
                    float(holding.cost_basis),
                    holding.currency.upper(),
                    holding.date_added.isoformat(),
                ),
            )

    def remove(self, ticker: str, market_code: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM holdings WHERE ticker = ? AND market = ?",
                (ticker.upper(), market_code.upper()),
            )
            return cur.rowcount > 0

    def get(self, ticker: str, market_code: str) -> Optional[Holding]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM holdings WHERE ticker = ? AND market = ?",
                (ticker.upper(), market_code.upper()),
            ).fetchone()
            return _row_to_holding(row) if row else None

    def all(self) -> list[Holding]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM holdings ORDER BY market, ticker"
            ).fetchall()
            return [_row_to_holding(r) for r in rows]

    def __iter__(self) -> Iterable[Holding]:
        return iter(self.all())


def _row_to_holding(row: sqlite3.Row) -> Holding:
    return Holding(
        ticker=row["ticker"],
        market_code=row["market"],
        shares=row["shares"],
        cost_basis=row["cost_basis"],
        currency=row["currency"],
        date_added=date.fromisoformat(row["date_added"]),
    )
