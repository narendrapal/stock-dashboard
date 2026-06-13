"""
Fetches live Nifty index constituent lists from NSE's public CSV endpoints.
Results are cached locally to avoid repeated network calls.
"""

import io
import json
import logging
import os
from datetime import datetime, timedelta
from typing import Optional

import requests
import pandas as pd

logger = logging.getLogger(__name__)

CACHE_FILE = os.path.join(os.path.dirname(__file__), "nifty_cache.json")
CACHE_HOURS = 24  # refresh constituent list once a day

NSE_INDEX_URLS = {
    "Nifty 500":       "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv",
    "Nifty 50":        "https://www.niftyindices.com/IndexConstituent/ind_nifty50list.csv",
    "Nifty Next 50":   "https://www.niftyindices.com/IndexConstituent/ind_niftynext50list.csv",
    "Nifty Midcap 150":"https://www.niftyindices.com/IndexConstituent/ind_niftymidcap150list.csv",
    "Nifty Smallcap 250":"https://www.niftyindices.com/IndexConstituent/ind_niftysmallcap250list.csv",
    "Nifty Bank":      "https://www.niftyindices.com/IndexConstituent/ind_niftybanklist.csv",
    "Nifty IT":        "https://www.niftyindices.com/IndexConstituent/ind_niftyitlist.csv",
}

_NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.niftyindices.com/",
    "Accept": "text/html,application/xhtml+xml,*/*",
}


def _load_cache() -> dict:
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_cache(data: dict):
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(data, f)
    except Exception as e:
        logger.warning(f"Could not save nifty cache: {e}")


def _is_fresh(cache: dict, index_name: str) -> bool:
    entry = cache.get(index_name, {})
    ts = entry.get("updated_at")
    if not ts:
        return False
    updated = datetime.fromisoformat(ts)
    return datetime.now() - updated < timedelta(hours=CACHE_HOURS)


def fetch_index_symbols(index_name: str, force_refresh: bool = False) -> list[str]:
    """
    Returns list of NSE symbols (with .NS suffix) for a given Nifty index.
    Fetches from NSE website, caches locally for 24 hours.
    Falls back to cache if network fails.
    """
    cache = _load_cache()

    if not force_refresh and _is_fresh(cache, index_name):
        logger.info(f"Using cached {index_name} ({len(cache[index_name]['symbols'])} symbols)")
        return cache[index_name]["symbols"]

    url = NSE_INDEX_URLS.get(index_name)
    if not url:
        logger.error(f"No URL configured for index: {index_name}")
        return cache.get(index_name, {}).get("symbols", [])

    try:
        resp = requests.get(url, headers=_NSE_HEADERS, timeout=15)
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text))

        # NSE CSV has a 'Symbol' column
        sym_col = next((c for c in df.columns if "symbol" in c.lower()), None)
        if sym_col is None:
            raise ValueError(f"No Symbol column in {index_name} CSV. Columns: {list(df.columns)}")

        symbols = [s.strip() + ".NS" for s in df[sym_col].dropna().tolist() if str(s).strip()]
        logger.info(f"Fetched {len(symbols)} symbols for {index_name} from NSE")

        cache[index_name] = {
            "symbols": symbols,
            "updated_at": datetime.now().isoformat(),
        }
        _save_cache(cache)
        return symbols

    except Exception as e:
        logger.error(f"Failed to fetch {index_name} from NSE: {e}")
        fallback = cache.get(index_name, {}).get("symbols", [])
        if fallback:
            logger.info(f"Using stale cache for {index_name} ({len(fallback)} symbols)")
        return fallback


def get_available_nse_indices() -> list[str]:
    return list(NSE_INDEX_URLS.keys())


def get_cache_info() -> dict:
    cache = _load_cache()
    return {
        k: {"count": len(v["symbols"]), "updated_at": v["updated_at"]}
        for k, v in cache.items()
    }
