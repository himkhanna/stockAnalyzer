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

CREATE TABLE IF NOT EXISTS watchlist (
    ticker      TEXT NOT NULL,
    market      TEXT NOT NULL,
    note        TEXT,
    date_added  TEXT NOT NULL,
    PRIMARY KEY (ticker, market)
);

CREATE TABLE IF NOT EXISTS signal_history (
    ticker       TEXT NOT NULL,
    market       TEXT NOT NULL,
    captured_at  TEXT NOT NULL,
    score_value  REAL NOT NULL,
    score_label  TEXT NOT NULL,
    PRIMARY KEY (ticker, market, captured_at)
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

    # --- Watchlist ---

    def watchlist_add(self, ticker: str, market_code: str, note: str = "") -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO watchlist (ticker, market, note, date_added)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(ticker, market) DO UPDATE SET note = excluded.note
                """,
                (ticker.upper(), market_code.upper(), note, date.today().isoformat()),
            )

    def watchlist_remove(self, ticker: str, market_code: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM watchlist WHERE ticker = ? AND market = ?",
                (ticker.upper(), market_code.upper()),
            )
            return cur.rowcount > 0

    def watchlist_all(self) -> list[tuple[str, str, str, str]]:
        """Return [(ticker, market, note, date_added), ...]."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT ticker, market, note, date_added FROM watchlist ORDER BY market, ticker"
            ).fetchall()
            return [(r["ticker"], r["market"], r["note"] or "", r["date_added"]) for r in rows]

    # --- Signal history ---

    def signal_record(self, ticker: str, market_code: str, value: float, label: str,
                      captured_at: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO signal_history
                    (ticker, market, captured_at, score_value, score_label)
                VALUES (?, ?, ?, ?, ?)
                """,
                (ticker.upper(), market_code.upper(), captured_at, float(value), label),
            )

    def signal_previous(self, ticker: str, market_code: str,
                        before: str) -> Optional[tuple[float, str, str]]:
        """Return (score_value, score_label, captured_at) for the most recent
        capture strictly before `before`. None if no prior record."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT score_value, score_label, captured_at
                FROM signal_history
                WHERE ticker = ? AND market = ? AND captured_at < ?
                ORDER BY captured_at DESC
                LIMIT 1
                """,
                (ticker.upper(), market_code.upper(), before),
            ).fetchone()
            if row is None:
                return None
            return (float(row["score_value"]), row["score_label"], row["captured_at"])


def _row_to_holding(row: sqlite3.Row) -> Holding:
    return Holding(
        ticker=row["ticker"],
        market_code=row["market"],
        shares=row["shares"],
        cost_basis=row["cost_basis"],
        currency=row["currency"],
        date_added=date.fromisoformat(row["date_added"]),
    )
