"""Resolve ISIN / company-name to an NSE ticker via Yahoo Finance search.

yfinance.Search hits Yahoo's free `/v1/finance/search` endpoint. We cache
results to `.ticker_cache.json` in the working dir so a 78-row portfolio
only resolves once. Manual overrides live in `.ticker_overrides.json` and
take precedence over the cache — edit that file if a lookup picks the
wrong listing (e.g. ADR instead of NSE).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

CACHE_FILE = Path(".ticker_cache.json")
OVERRIDES_FILE = Path(".ticker_overrides.json")


@dataclass(frozen=True)
class Resolution:
    bare_symbol: str       # e.g. "EXIDEIND"  (no .NS)
    qualified: str         # e.g. "EXIDEIND.NS"
    source: str            # "override" | "cache" | "yahoo_isin" | "yahoo_name" | "fallback"
    confidence: str        # "high" | "medium" | "low"


class TickerResolver:
    def __init__(
        self,
        cache_path: Path = CACHE_FILE,
        overrides_path: Path = OVERRIDES_FILE,
        market_suffix: str = ".NS",
    ) -> None:
        self.cache_path = cache_path
        self.overrides_path = overrides_path
        self.market_suffix = market_suffix
        self._cache = self._load(cache_path)
        self._overrides = self._load(overrides_path)

    @staticmethod
    def _load(p: Path) -> dict:
        if not p.exists():
            return {}
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_cache(self) -> None:
        self.cache_path.write_text(json.dumps(self._cache, indent=2, sort_keys=True), encoding="utf-8")

    def resolve(self, *, isin: str = "", name: str = "", fallback: str = "") -> Optional[Resolution]:
        """Resolve to an NSE ticker. Returns None if nothing usable found."""
        isin = (isin or "").strip().upper()
        name = (name or "").strip()
        fallback = (fallback or "").strip().upper()

        # 1. Manual override by ISIN wins.
        if isin and isin in self._overrides:
            sym = self._overrides[isin].upper().replace(self.market_suffix, "")
            return Resolution(sym, sym + self.market_suffix, "override", "high")

        # 2. Cache.
        key = isin or f"name:{name}" or f"fb:{fallback}"
        if key in self._cache:
            sym = self._cache[key]
            if sym:
                return Resolution(sym, sym + self.market_suffix, "cache", "high")
            return None  # cached as unresolvable

        # 3. Yahoo search (ISIN first, then name).
        if isin:
            sym = self._yahoo_search(isin)
            if sym:
                self._cache[key] = sym
                self._save_cache()
                return Resolution(sym, sym + self.market_suffix, "yahoo_isin", "high")
        if name:
            sym = self._yahoo_search(name)
            if sym:
                self._cache[key] = sym
                self._save_cache()
                return Resolution(sym, sym + self.market_suffix, "yahoo_name", "medium")

        # 4. Give up. Cache the miss so repeated imports don't re-hit Yahoo.
        self._cache[key] = ""
        self._save_cache()
        return None

    def _yahoo_search(self, query: str) -> Optional[str]:
        """Hit Yahoo's search endpoint, return the bare NSE symbol of the first
        match whose ticker ends with the market suffix. None if nothing matches."""
        try:
            import yfinance as yf
        except ImportError:
            return None
        try:
            search = yf.Search(query, max_results=8)
            quotes = search.quotes or []
        except Exception:
            return None
        for q in quotes:
            sym = (q.get("symbol") or "").upper()
            if sym.endswith(self.market_suffix):
                return sym[: -len(self.market_suffix)]
        # No NSE match. Some Indian listings come back as e.g. "RELIANCE.NS"
        # always; if every hit is non-NSE, the company likely isn't on NSE
        # under this name (could be BSE-only, or an ADR, etc.).
        return None
