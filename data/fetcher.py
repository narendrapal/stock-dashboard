"""
Data fetching layer using yfinance.
Handles caching, retries, and multi-timeframe OHLCV data.
"""

import time
import logging
from datetime import datetime, timedelta
from typing import Optional

import yfinance as yf
import pandas as pd

logger = logging.getLogger(__name__)

# Simple in-memory cache: {cache_key: (timestamp, dataframe)}
_cache: dict = {}


def _cache_get(key: str, ttl: int) -> Optional[pd.DataFrame]:
    if key in _cache:
        ts, df = _cache[key]
        if time.time() - ts < ttl:
            return df
    return None


def _cache_set(key: str, df: pd.DataFrame):
    _cache[key] = (time.time(), df)


def clear_cache():
    """Force-clear the entire in-memory cache (called on manual refresh)."""
    _cache.clear()
    logger.info("Cache cleared.")


def fetch_ohlcv(
    symbol: str,
    period: str = "3mo",
    interval: str = "1d",
    ttl: int = 300,
) -> Optional[pd.DataFrame]:
    """
    Fetch OHLCV data for a symbol. Returns None on failure.
    Uses in-memory cache to avoid hammering yfinance.
    """
    cache_key = f"{symbol}_{period}_{interval}"
    cached = _cache_get(cache_key, ttl)
    if cached is not None:
        return cached

    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period, interval=interval, auto_adjust=True)
        if df.empty:
            logger.warning(f"No data returned for {symbol}")
            return None
        df.index = pd.to_datetime(df.index)
        _cache_set(cache_key, df)
        return df
    except Exception as e:
        logger.error(f"Error fetching {symbol}: {e}")
        return None


def fetch_quote(symbol: str, ttl: int = 60) -> dict:
    """
    Fetch latest quote info for a symbol: price, change, volume, market cap etc.
    """
    cache_key = f"quote_{symbol}"
    cached = _cache_get(cache_key, ttl)
    if cached is not None:
        return cached

    try:
        ticker = yf.Ticker(symbol)
        info = ticker.fast_info
        hist = ticker.history(period="2d", interval="1d", auto_adjust=True)

        result = {
            "symbol": symbol,
            "last_price": None,
            "prev_close": None,
            "price_change": None,
            "price_change_pct": None,
            "volume": None,
            "market_cap": None,
            "day_high": None,
            "day_low": None,
        }

        if not hist.empty and len(hist) >= 1:
            result["last_price"] = round(float(hist["Close"].iloc[-1]), 2)
            result["day_high"] = round(float(hist["High"].iloc[-1]), 2)
            result["day_low"] = round(float(hist["Low"].iloc[-1]), 2)
            result["volume"] = int(hist["Volume"].iloc[-1])

        if not hist.empty and len(hist) >= 2:
            result["prev_close"] = round(float(hist["Close"].iloc[-2]), 2)
            chg = result["last_price"] - result["prev_close"]
            result["price_change"] = round(chg, 2)
            result["price_change_pct"] = round((chg / result["prev_close"]) * 100, 2)

        try:
            result["market_cap"] = getattr(info, "market_cap", None)
        except Exception:
            pass

        _cache_set(cache_key, result)
        return result
    except Exception as e:
        logger.error(f"Error fetching quote for {symbol}: {e}")
        return {"symbol": symbol, "last_price": None, "price_change_pct": None}


def fetch_bulk_quotes(symbols: list, ttl: int = 60) -> list[dict]:
    """Fetch quotes for multiple symbols. Returns list of quote dicts."""
    results = []
    for sym in symbols:
        q = fetch_quote(sym, ttl=ttl)
        results.append(q)
        time.sleep(0.05)  # be gentle with yfinance
    return results
