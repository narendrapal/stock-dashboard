"""
Disk persistence for:
  - Screener results (so page reload shows last data, no forced refresh)
  - Custom watchlists (user-managed lists with add/remove)
"""

import json
import logging
import os
from datetime import datetime

import pandas as pd

logger = logging.getLogger(__name__)

CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")
WATCHLIST_FILE = os.path.join(CACHE_DIR, "watchlists.json")


def _screen_cache_path(watchlist_name: str, timeframe: str) -> str:
    safe = watchlist_name.replace(" ", "_").replace("/", "-")
    return os.path.join(CACHE_DIR, f"screen_{safe}_{timeframe}.json")


# ── Screener cache ─────────────────────────────────────────────────────────────

def save_screen_result(watchlist_name: str, timeframe: str, df: pd.DataFrame):
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = _screen_cache_path(watchlist_name, timeframe)
    try:
        payload = {
            "saved_at": datetime.now().isoformat(),
            "watchlist": watchlist_name,
            "timeframe": timeframe,
            "data": df.to_dict(orient="records"),
        }
        with open(path, "w") as f:
            json.dump(payload, f)
    except Exception as e:
        logger.warning(f"Could not save screen cache: {e}")


def load_screen_result(watchlist_name: str, timeframe: str) -> tuple[pd.DataFrame | None, str | None]:
    """Returns (DataFrame, saved_at_str) or (None, None) if no cache."""
    path = _screen_cache_path(watchlist_name, timeframe)
    if not os.path.exists(path):
        return None, None
    try:
        with open(path) as f:
            payload = json.load(f)
        df = pd.DataFrame(payload["data"])
        saved_at = payload.get("saved_at", "")
        return df, saved_at
    except Exception as e:
        logger.warning(f"Could not load screen cache: {e}")
        return None, None


# ── Custom watchlists ──────────────────────────────────────────────────────────

DEFAULT_WATCHLISTS = {
    "My Watchlist": [
        "RELIANCE.NS", "TCS.NS", "INFY.NS", "SBIN.NS", "HDFCBANK.NS",
        "ICICIBANK.NS", "AXISBANK.NS", "TATAMOTORS.NS", "WIPRO.NS", "BAJFINANCE.NS",
    ]
}


def load_custom_watchlists() -> dict:
    os.makedirs(CACHE_DIR, exist_ok=True)
    if not os.path.exists(WATCHLIST_FILE):
        _save_custom_watchlists(DEFAULT_WATCHLISTS)
        return dict(DEFAULT_WATCHLISTS)
    try:
        with open(WATCHLIST_FILE) as f:
            return json.load(f)
    except Exception:
        return dict(DEFAULT_WATCHLISTS)


def _save_custom_watchlists(watchlists: dict):
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(WATCHLIST_FILE, "w") as f:
        json.dump(watchlists, f, indent=2)


def save_custom_watchlists(watchlists: dict):
    _save_custom_watchlists(watchlists)


def add_symbol_to_watchlist(watchlist_name: str, symbol: str) -> dict:
    wl = load_custom_watchlists()
    if watchlist_name not in wl:
        wl[watchlist_name] = []
    if symbol not in wl[watchlist_name]:
        wl[watchlist_name].append(symbol)
        save_custom_watchlists(wl)
    return wl


def remove_symbol_from_watchlist(watchlist_name: str, symbol: str) -> dict:
    wl = load_custom_watchlists()
    if watchlist_name in wl and symbol in wl[watchlist_name]:
        wl[watchlist_name].remove(symbol)
        save_custom_watchlists(wl)
    return wl


def create_watchlist(name: str) -> dict:
    wl = load_custom_watchlists()
    if name not in wl:
        wl[name] = []
        save_custom_watchlists(wl)
    return wl


def delete_watchlist(name: str) -> dict:
    wl = load_custom_watchlists()
    wl.pop(name, None)
    save_custom_watchlists(wl)
    return wl
