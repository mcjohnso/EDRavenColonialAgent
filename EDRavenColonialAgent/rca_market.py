"""
Station market availability — reads Market.json to know which commodities the docked
station currently sells (Stock > 0).

Elite writes Market.json into the journal directory on every Market event (the journal
'Market' event itself carries no items). SrvSurvey uses the same file to dim needed
commodities that are not for sale where you are docked.

Kept free of EDMC imports except a small, guarded journal-dir resolver, so the parsing
is unit-testable.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional, Set

from rca_colony import normalize_name


def resolve_journal_dir() -> Optional[str]:
    """Best-effort journal directory: EDMC config first, then Elite's default location."""
    try:
        from config import config  # EDMC-provided
        journal_dir = config.get_str("journaldir")
        if journal_dir and os.path.isdir(journal_dir):
            return journal_dir
        # EDMC exposes the platform default too
        default = getattr(config, "default_journal_dir", None)
        if default and os.path.isdir(default):
            return default
    except Exception:
        pass

    # Fallback: Elite's default Windows Saved Games path
    candidate = os.path.join(
        os.path.expanduser("~"),
        "Saved Games", "Frontier Developments", "Elite Dangerous",
    )
    return candidate if os.path.isdir(candidate) else None


def read_market_file(journal_dir: Optional[str]) -> Optional[Dict[str, Any]]:
    """Parse Market.json from journal_dir; return the dict, or None on any failure."""
    if not journal_dir:
        return None
    path = os.path.join(journal_dir, "Market.json")
    try:
        # utf-8-sig tolerates an optional BOM in game-written files
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def available_commodities(market: Optional[Dict[str, Any]]) -> Set[str]:
    """Set of normalized commodity names with Stock > 0 in a parsed Market.json dict."""
    if not market:
        return set()
    out: Set[str] = set()
    for item in market.get("Items", []) or []:
        try:
            stock = int(item.get("Stock", 0))
        except (TypeError, ValueError):
            stock = 0
        if stock > 0:
            name = normalize_name(item.get("Name", ""))
            if name:
                out.add(name)
    return out


def load_market_availability(market_id: Optional[int] = None,
                             journal_dir: Optional[str] = None) -> Set[str]:
    """Convenience: resolve dir, read Market.json, return available commodity names.

    If market_id is given, only return data when Market.json is for that MarketID
    (avoids showing a stale market after re-docking elsewhere).
    """
    if journal_dir is None:
        journal_dir = resolve_journal_dir()
    market = read_market_file(journal_dir)
    if market is None:
        return set()
    if market_id is not None and market.get("MarketID") != market_id:
        return set()
    return available_commodities(market)
