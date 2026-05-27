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

CREATE TABLE IF NOT EXISTS alerts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker      TEXT NOT NULL,
    market      TEXT NOT NULL,
    kind        TEXT NOT NULL,    -- price_above|price_below|rsi_above|rsi_below|
                                  -- score_flip_buy|score_flip_sell|
                                  -- pct_drop_day|pct_rise_day|
                                  -- score_at_or_above|score_at_or_below
    threshold   REAL NOT NULL,
    note        TEXT,
    active      INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL,
    last_fired_at TEXT
);
CREATE INDEX IF NOT EXISTS alerts_active_ix ON alerts(active);
CREATE INDEX IF NOT EXISTS alerts_ticker_ix ON alerts(ticker, market);

CREATE TABLE IF NOT EXISTS alert_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id    INTEGER NOT NULL,
    ticker      TEXT NOT NULL,
    market      TEXT NOT NULL,
    kind        TEXT NOT NULL,
    threshold   REAL NOT NULL,
    fired_at    TEXT NOT NULL,
    triggered_value REAL,
    message     TEXT,
    acknowledged INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(alert_id) REFERENCES alerts(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS alert_events_ack_ix ON alert_events(acknowledged, fired_at DESC);

CREATE TABLE IF NOT EXISTS broker_config (
    broker        TEXT PRIMARY KEY,   -- e.g. "icici_breeze"
    api_key       TEXT,
    api_secret    TEXT,                -- stored locally; never exposed via the API
    session_token TEXT,
    session_expires_at TEXT,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS broker_code_map (
    broker          TEXT NOT NULL,   -- "icici_breeze"
    exchange_ticker TEXT NOT NULL,   -- bare NSE/BSE ticker, uppercase (e.g. "SBIN")
    broker_code     TEXT NOT NULL,   -- broker's stock_code (e.g. "STABAN")
    source          TEXT NOT NULL,   -- "holdings_sync" | "chain_ok" | "manual"
    updated_at      TEXT NOT NULL,
    PRIMARY KEY (broker, exchange_ticker)
);

CREATE TABLE IF NOT EXISTS realized_gains (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker       TEXT NOT NULL,
    market       TEXT NOT NULL,
    qty          REAL NOT NULL,
    gain_amount  REAL NOT NULL,            -- positive = gain, negative = loss
    currency     TEXT NOT NULL,
    term         TEXT NOT NULL,            -- "short" | "long"
    realized_at  TEXT NOT NULL,            -- ISO date
    fy           TEXT NOT NULL,            -- "2025-26" (India) or "2025" (US)
    note         TEXT,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS realized_gains_fy_ix ON realized_gains(fy, market);
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

    def remove_by_markets(self, market_codes: Iterable[str]) -> int:
        codes = tuple(m.upper() for m in market_codes)
        if not codes:
            return 0
        placeholders = ",".join("?" for _ in codes)
        with self._connect() as conn:
            cur = conn.execute(
                f"DELETE FROM holdings WHERE market IN ({placeholders})",
                codes,
            )
            return cur.rowcount

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


    # --- Alerts ---

    def alert_add(self, ticker: str, market_code: str, kind: str,
                  threshold: float, note: str = "") -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO alerts (ticker, market, kind, threshold, note, active, created_at)
                VALUES (?, ?, ?, ?, ?, 1, ?)
                """,
                (ticker.upper(), market_code.upper(), kind, float(threshold),
                 note, date.today().isoformat()),
            )
            return int(cur.lastrowid)

    def alert_remove(self, alert_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM alerts WHERE id = ?", (alert_id,))
            return cur.rowcount > 0

    def alert_set_active(self, alert_id: int, active: bool) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE alerts SET active = ? WHERE id = ?",
                (1 if active else 0, alert_id),
            )
            return cur.rowcount > 0

    def alerts_list(self, *, active_only: bool = False) -> list[dict]:
        sql = (
            "SELECT id, ticker, market, kind, threshold, note, active, "
            "created_at, last_fired_at FROM alerts"
        )
        if active_only:
            sql += " WHERE active = 1"
        sql += " ORDER BY active DESC, market, ticker, id"
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(sql).fetchall()]

    def alert_mark_fired(self, alert_id: int, fired_at: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE alerts SET last_fired_at = ? WHERE id = ?",
                (fired_at, alert_id),
            )

    def alert_event_add(self, *, alert_id: int, ticker: str, market_code: str,
                        kind: str, threshold: float, fired_at: str,
                        triggered_value: Optional[float], message: str) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO alert_events
                    (alert_id, ticker, market, kind, threshold, fired_at,
                     triggered_value, message, acknowledged)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (alert_id, ticker.upper(), market_code.upper(), kind,
                 float(threshold), fired_at,
                 float(triggered_value) if triggered_value is not None else None,
                 message),
            )
            return int(cur.lastrowid)

    def alert_events_list(self, *, unacknowledged_only: bool = False,
                          limit: int = 100) -> list[dict]:
        sql = (
            "SELECT id, alert_id, ticker, market, kind, threshold, fired_at, "
            "triggered_value, message, acknowledged FROM alert_events"
        )
        if unacknowledged_only:
            sql += " WHERE acknowledged = 0"
        sql += " ORDER BY fired_at DESC LIMIT ?"
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(sql, (limit,)).fetchall()]

    def alert_event_ack(self, event_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE alert_events SET acknowledged = 1 WHERE id = ?",
                (event_id,),
            )
            return cur.rowcount > 0

    def alert_event_ack_all(self) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE alert_events SET acknowledged = 1 WHERE acknowledged = 0"
            )
            return cur.rowcount

    # --- Broker config ---

    def broker_get(self, broker: str) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT broker, api_key, api_secret, session_token, "
                "session_expires_at, updated_at FROM broker_config WHERE broker = ?",
                (broker,),
            ).fetchone()
            return dict(row) if row else None

    def broker_set_credentials(self, broker: str, api_key: str, api_secret: str) -> None:
        from datetime import datetime as _dt
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO broker_config (broker, api_key, api_secret, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(broker) DO UPDATE SET
                    api_key = excluded.api_key,
                    api_secret = excluded.api_secret,
                    updated_at = excluded.updated_at
                """,
                (broker, api_key, api_secret, _dt.utcnow().isoformat()),
            )

    def broker_set_session(self, broker: str, session_token: str,
                           session_expires_at: str) -> None:
        from datetime import datetime as _dt
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE broker_config
                SET session_token = ?, session_expires_at = ?, updated_at = ?
                WHERE broker = ?
                """,
                (session_token, session_expires_at, _dt.utcnow().isoformat(), broker),
            )

    def broker_clear(self, broker: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM broker_config WHERE broker = ?",
                (broker,),
            )
            return cur.rowcount > 0

    # --- Broker stock-code dictionary ---

    def broker_code_get(self, broker: str, exchange_ticker: str) -> Optional[str]:
        """Return the broker's internal stock_code for an exchange ticker, or None."""
        if not exchange_ticker:
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT broker_code FROM broker_code_map "
                "WHERE broker = ? AND exchange_ticker = ?",
                (broker, exchange_ticker.upper()),
            ).fetchone()
            return row["broker_code"] if row else None

    def broker_code_upsert(self, broker: str, exchange_ticker: str,
                           broker_code: str, source: str) -> None:
        """Record an (exchange_ticker → broker_code) mapping. Idempotent."""
        if not exchange_ticker or not broker_code:
            return
        from datetime import datetime as _dt
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO broker_code_map
                    (broker, exchange_ticker, broker_code, source, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(broker, exchange_ticker) DO UPDATE SET
                    broker_code = excluded.broker_code,
                    source      = excluded.source,
                    updated_at  = excluded.updated_at
                """,
                (broker, exchange_ticker.upper(), broker_code.upper(),
                 source, _dt.utcnow().isoformat()),
            )

    def broker_code_all(self, broker: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT exchange_ticker, broker_code, source, updated_at "
                "FROM broker_code_map WHERE broker = ? ORDER BY exchange_ticker",
                (broker,),
            ).fetchall()
            return [dict(r) for r in rows]

    # --- Realized gains (capital gains running tally) ---

    def realized_gain_add(self, *, ticker: str, market: str, qty: float,
                          gain_amount: float, currency: str, term: str,
                          realized_at: str, fy: str, note: str = "") -> int:
        from datetime import datetime as _dt
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO realized_gains
                  (ticker, market, qty, gain_amount, currency, term,
                   realized_at, fy, note, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (ticker.upper(), market.upper(), float(qty), float(gain_amount),
                 currency.upper(), term, realized_at, fy, note,
                 _dt.utcnow().isoformat()),
            )
            return int(cur.lastrowid)

    def realized_gain_remove(self, gain_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM realized_gains WHERE id = ?", (gain_id,),
            )
            return cur.rowcount > 0

    def realized_gains_list(self, *, fy: Optional[str] = None) -> list[dict]:
        sql = (
            "SELECT id, ticker, market, qty, gain_amount, currency, term, "
            "realized_at, fy, note, created_at FROM realized_gains"
        )
        params: tuple = ()
        if fy:
            sql += " WHERE fy = ?"
            params = (fy,)
        sql += " ORDER BY realized_at DESC, id DESC"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]


def _row_to_holding(row: sqlite3.Row) -> Holding:
    return Holding(
        ticker=row["ticker"],
        market_code=row["market"],
        shares=row["shares"],
        cost_basis=row["cost_basis"],
        currency=row["currency"],
        date_added=date.fromisoformat(row["date_added"]),
    )
