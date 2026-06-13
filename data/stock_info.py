"""
Fetches and caches stock metadata: company name, sector, 52-week high.
Cached in data/cache/stock_info.json — refreshed every 7 days.
"""

import json
import logging
import os
import time
from datetime import datetime, timedelta

import yfinance as yf

logger = logging.getLogger(__name__)

CACHE_FILE = os.path.join(os.path.dirname(__file__), "cache", "stock_info.json")
CACHE_DAYS = 7


def _load() -> dict:
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save(data: dict):
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(data, f)
    except Exception as e:
        logger.warning(f"Could not save stock_info cache: {e}")


def _is_fresh(entry: dict) -> bool:
    ts = entry.get("cached_at")
    if not ts:
        return False
    return datetime.now() - datetime.fromisoformat(ts) < timedelta(days=CACHE_DAYS)


def get_stock_info(symbol: str) -> dict:
    """Returns {name, sector, week52_high} for a symbol, using disk cache."""
    cache = _load()
    if symbol in cache and _is_fresh(cache[symbol]):
        return cache[symbol]

    result = {"symbol": symbol, "name": symbol.replace(".NS", "").replace(".BO", ""),
              "sector": "—", "week52_high": None, "cached_at": datetime.now().isoformat()}
    try:
        info = yf.Ticker(symbol).info
        result["name"] = info.get("shortName") or info.get("longName") or result["name"]
        result["sector"] = info.get("sector") or info.get("industry") or "—"
        result["week52_high"] = info.get("fiftyTwoWeekHigh")
    except Exception as e:
        logger.debug(f"Info fetch failed for {symbol}: {e}")

    cache[symbol] = result
    _save(cache)
    return result


def get_bulk_info(symbols: list) -> dict:
    """Returns {symbol: {name, sector, week52_high}} for a list. Fetches missing ones."""
    cache = _load()
    missing = [s for s in symbols if s not in cache or not _is_fresh(cache[s])]

    for sym in missing:
        result = {"symbol": sym, "name": sym.replace(".NS", "").replace(".BO", ""),
                  "sector": "—", "week52_high": None, "cached_at": datetime.now().isoformat()}
        try:
            info = yf.Ticker(sym).info
            result["name"] = info.get("shortName") or info.get("longName") or result["name"]
            result["sector"] = info.get("sector") or info.get("industry") or "—"
            result["week52_high"] = info.get("fiftyTwoWeekHigh")
            time.sleep(0.05)
        except Exception as e:
            logger.debug(f"Info fetch failed for {sym}: {e}")
        cache[sym] = result

    if missing:
        _save(cache)

    return {s: cache.get(s, {"name": s, "sector": "—", "week52_high": None}) for s in symbols}
