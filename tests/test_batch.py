"""Tests for batch digest generation.

The LLM call is bypassed (run_llm=False) so these run fast and offline.
Data source is mocked. We verify: file layout, skip-on-exists, force,
failure isolation, and that the index gets written.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from portfolio_intel.batch import BatchItem, run_batch
from portfolio_intel.data.models import Quote
from portfolio_intel.markets import Market


def _ohlcv(seed: int = 0, n: int = 260) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    trend = np.linspace(100, 150, n) + rng.normal(0, 1, n)
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {"open": trend, "high": trend + 1, "low": trend - 1,
         "close": trend, "volume": rng.integers(800, 1200, n)},
        index=idx,
    )


def _mock_source(seed: int = 0) -> MagicMock:
    ds = MagicMock()
    ds.get_history.return_value = _ohlcv(seed)
    ds.get_quote.return_value = Quote(
        symbol="X", market_code="US", price=150.0, currency="USD",
        as_of=datetime.now(timezone.utc), previous_close=149.0, stale=False,
    )
    ds.get_news.return_value = []
    return ds


def test_batch_writes_one_md_per_ticker_and_index(tmp_path):
    items = [
        BatchItem("AAPL", Market.US),
        BatchItem("RELIANCE", Market.NSE),
    ]
    outcomes = run_batch(
        items,
        data_source=_mock_source(),
        out_dir=tmp_path,
        run_llm=False,
    )
    today = date.today().isoformat()
    day_dir = tmp_path / today
    assert (day_dir / "AAPL.US.md").exists()
    assert (day_dir / "RELIANCE.NSE.md").exists()
    assert (day_dir / "index.md").exists()
    assert all(o.status == "ok" for o in outcomes)


def test_batch_index_contains_each_ticker(tmp_path):
    items = [BatchItem("AAPL", Market.US), BatchItem("MSFT", Market.US)]
    run_batch(items, data_source=_mock_source(), out_dir=tmp_path, run_llm=False)
    today = date.today().isoformat()
    idx = (tmp_path / today / "index.md").read_text(encoding="utf-8")
    assert "AAPL.US" in idx
    assert "MSFT.US" in idx
    assert "uptrend" in idx  # trend label rendered


def test_batch_skips_existing_files_unless_force(tmp_path):
    items = [BatchItem("AAPL", Market.US)]
    run_batch(items, data_source=_mock_source(), out_dir=tmp_path, run_llm=False)

    out2 = run_batch(items, data_source=_mock_source(), out_dir=tmp_path, run_llm=False)
    assert out2[0].status == "skipped"

    out3 = run_batch(
        items, data_source=_mock_source(), out_dir=tmp_path, run_llm=False, force=True,
    )
    assert out3[0].status == "ok"


def test_batch_isolates_failures(tmp_path):
    """One failing ticker must not block the others."""
    ds_ok = _mock_source()
    ds_bad = MagicMock()
    ds_bad.get_history.side_effect = RuntimeError("boom")

    # The orchestrator gets a single data source — to test failure isolation
    # we attach a side_effect that raises only for the second call.
    ds = MagicMock()
    call_state = {"n": 0}

    def hist(*a, **kw):
        call_state["n"] += 1
        if call_state["n"] == 2:
            raise RuntimeError("boom on MSFT")
        return _ohlcv(seed=call_state["n"])

    ds.get_history.side_effect = hist
    ds.get_quote.return_value = ds_ok.get_quote.return_value
    ds.get_news.return_value = []

    items = [BatchItem("AAPL", Market.US), BatchItem("MSFT", Market.US), BatchItem("GOOG", Market.US)]
    outcomes = run_batch(items, data_source=ds, out_dir=tmp_path, run_llm=False)

    statuses = {o.item.symbol: o.status for o in outcomes}
    assert statuses == {"AAPL": "ok", "MSFT": "failed", "GOOG": "ok"}

    today = date.today().isoformat()
    assert (tmp_path / today / "MSFT.US.error.txt").exists()
    idx = (tmp_path / today / "index.md").read_text(encoding="utf-8")
    assert "failed" in idx.lower()


def test_batch_progress_callback_fires_per_item(tmp_path):
    items = [BatchItem("AAPL", Market.US), BatchItem("MSFT", Market.US)]
    seen: list[tuple[int, int, str]] = []

    def cb(i, total, outcome):
        seen.append((i, total, outcome.item.symbol))

    run_batch(items, data_source=_mock_source(), out_dir=tmp_path, run_llm=False,
              on_progress=cb)
    assert seen == [(1, 2, "AAPL"), (2, 2, "MSFT")]
