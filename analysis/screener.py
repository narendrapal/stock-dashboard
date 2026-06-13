"""
Screener engine: fetches data, computes indicators, applies filters.
"""

import logging

import pandas as pd

from data.fetcher import fetch_ohlcv, fetch_quote
from analysis.indicators import compute_all, compute_rsi
from config import TIMEFRAMES, CACHE_TTL_SECONDS

logger = logging.getLogger(__name__)


def _get_rsi(symbol: str, timeframe: str, period: int, ttl: int) -> float | None:
    tf = TIMEFRAMES.get(timeframe, TIMEFRAMES["Daily"])
    df = fetch_ohlcv(symbol, period=tf["period"], interval=tf["interval"], ttl=ttl)
    return compute_rsi(df, period=period) if df is not None else None


def screen_symbol(
    symbol: str,
    timeframe: str = "Daily",
    rsi_period: int = 14,
    ttl: int = CACHE_TTL_SECONDS,
    stock_info: dict = None,
) -> dict:
    """
    Full analysis for one symbol. Includes multi-TF RSI, MA flags, 52W high proximity.
    stock_info: optional pre-fetched {name, sector, week52_high} dict.
    """
    tf = TIMEFRAMES.get(timeframe, TIMEFRAMES["Daily"])
    df = fetch_ohlcv(symbol, period=tf["period"], interval=tf["interval"], ttl=ttl)
    quote = fetch_quote(symbol, ttl=ttl)

    info = stock_info or {}
    last_price = quote.get("last_price")
    week52_high = info.get("week52_high")
    near_52w_high = (
        last_price is not None and week52_high and week52_high > 0
        and last_price >= week52_high * 0.97
    )

    row = {
        "Symbol": symbol,
        "Name": info.get("name", symbol.replace(".NS", "").replace(".BO", "")),
        "Sector": info.get("sector", "—"),
        "Price": last_price,
        "Change%": quote.get("price_change_pct"),
        "Volume": quote.get("volume"),
        "52W High": week52_high,
        "Near 52W High": near_52w_high,
        "price_change_pct": quote.get("price_change_pct"),
        "RSI_W": None,
        "RSI_M": None,
    }

    if df is not None and not df.empty:
        indicators = compute_all(df, rsi_period=rsi_period)
        row.update(indicators)
        # Multi-timeframe RSI (weekly + monthly always fetched)
        if timeframe != "Weekly":
            row["RSI_W"] = _get_rsi(symbol, "Weekly", rsi_period, ttl)
        else:
            row["RSI_W"] = row.get("RSI")
        if timeframe != "Monthly":
            row["RSI_M"] = _get_rsi(symbol, "Monthly", rsi_period, ttl)
        else:
            row["RSI_M"] = row.get("RSI")
        # Rename daily RSI for clarity when multi-TF shown
        row["RSI_D"] = row.get("RSI")
    else:
        row.update({"RSI": None, "RSI_D": None, "SMA_20": None, "SMA_50": None,
                    "SMA_200": None, "EMA_20": None, "volume_ratio": None, "ATR": None,
                    "above_sma20": False, "above_sma50": False, "above_sma200": False})

    return row


def screen_watchlist(
    symbols: list,
    timeframe: str = "Daily",
    rsi_period: int = 14,
    ttl: int = CACHE_TTL_SECONDS,
) -> pd.DataFrame:
    """
    Screen all symbols in a watchlist. Returns a DataFrame.
    """
    rows = []
    for sym in symbols:
        try:
            row = screen_symbol(sym, timeframe=timeframe, rsi_period=rsi_period, ttl=ttl)
            rows.append(row)
        except Exception as e:
            logger.error(f"Error screening {sym}: {e}")
            rows.append({"Symbol": sym})

    return pd.DataFrame(rows)


def apply_filters(
    df: pd.DataFrame,
    rsi_min: float = 0,
    rsi_max: float = 100,
    volume_multiplier: float = 0.0,
    price_change_min: float = -100,
    price_change_max: float = 100,
) -> pd.DataFrame:
    """Apply UI filter conditions to screener DataFrame."""
    filtered = df.copy()

    if "RSI" in filtered.columns:
        mask = filtered["RSI"].isna() | (
            (filtered["RSI"] >= rsi_min) & (filtered["RSI"] <= rsi_max)
        )
        filtered = filtered[mask]

    if "volume_ratio" in filtered.columns and volume_multiplier > 0:
        mask = filtered["volume_ratio"].isna() | (filtered["volume_ratio"] >= volume_multiplier)
        filtered = filtered[mask]

    if "Change%" in filtered.columns:
        mask = filtered["Change%"].isna() | (
            (filtered["Change%"] >= price_change_min) &
            (filtered["Change%"] <= price_change_max)
        )
        filtered = filtered[mask]

    return filtered


def check_rules_for_symbol(symbol: str, rules: list, timeframe: str = "Daily") -> list:
    """
    Checks notification rules for a symbol.
    Returns list of triggered rule names.
    """
    triggered = []
    row = screen_symbol(symbol, timeframe=timeframe)

    ops = {
        ">": lambda a, b: a is not None and a > b,
        "<": lambda a, b: a is not None and a < b,
        ">=": lambda a, b: a is not None and a >= b,
        "<=": lambda a, b: a is not None and a <= b,
        "==": lambda a, b: a is not None and a == b,
    }

    for rule in rules:
        if not rule.get("enabled", False):
            continue
        field = rule["field"]
        op = rule["operator"]
        val = rule["value"]
        actual = row.get(field)
        if ops.get(op, lambda a, b: False)(actual, val):
            triggered.append({
                "rule": rule["name"],
                "symbol": symbol,
                "field": field,
                "actual": actual,
                "threshold": val,
            })

    return triggered
