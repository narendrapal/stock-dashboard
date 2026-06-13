"""
Technical indicator calculations using pandas-ta.
"""

import logging
from typing import Optional

import pandas as pd
import pandas_ta as ta

logger = logging.getLogger(__name__)


def compute_rsi(df: pd.DataFrame, period: int = 14) -> Optional[float]:
    """Returns the latest RSI value."""
    try:
        if df is None or len(df) < period + 1:
            return None
        rsi_series = ta.rsi(df["Close"], length=period)
        if rsi_series is None or rsi_series.empty:
            return None
        val = rsi_series.dropna().iloc[-1]
        return round(float(val), 2)
    except Exception as e:
        logger.error(f"RSI error: {e}")
        return None


def compute_macd(df: pd.DataFrame) -> dict:
    """Returns dict with macd, signal, histogram latest values."""
    try:
        if df is None or len(df) < 35:
            return {}
        macd_df = ta.macd(df["Close"])
        if macd_df is None or macd_df.empty:
            return {}
        last = macd_df.dropna().iloc[-1]
        cols = macd_df.columns.tolist()
        return {
            "macd": round(float(last[cols[0]]), 4),
            "histogram": round(float(last[cols[1]]), 4),
            "signal": round(float(last[cols[2]]), 4),
        }
    except Exception as e:
        logger.error(f"MACD error: {e}")
        return {}


def compute_sma(df: pd.DataFrame, period: int) -> Optional[float]:
    try:
        if df is None or len(df) < period:
            return None
        sma = ta.sma(df["Close"], length=period)
        if sma is None or sma.empty:
            return None
        return round(float(sma.dropna().iloc[-1]), 2)
    except Exception as e:
        logger.error(f"SMA({period}) error: {e}")
        return None


def compute_ema(df: pd.DataFrame, period: int) -> Optional[float]:
    try:
        if df is None or len(df) < period:
            return None
        ema = ta.ema(df["Close"], length=period)
        if ema is None or ema.empty:
            return None
        return round(float(ema.dropna().iloc[-1]), 2)
    except Exception as e:
        logger.error(f"EMA({period}) error: {e}")
        return None


def compute_volume_ratio(df: pd.DataFrame, avg_period: int = 20) -> Optional[float]:
    """Current volume / avg volume over last N days."""
    try:
        if df is None or len(df) < avg_period + 1:
            return None
        avg_vol = df["Volume"].iloc[-avg_period - 1 : -1].mean()
        if avg_vol == 0:
            return None
        curr_vol = df["Volume"].iloc[-1]
        return round(float(curr_vol / avg_vol), 2)
    except Exception as e:
        logger.error(f"Volume ratio error: {e}")
        return None


def compute_atr(df: pd.DataFrame, period: int = 14) -> Optional[float]:
    try:
        if df is None or len(df) < period + 1:
            return None
        atr = ta.atr(df["High"], df["Low"], df["Close"], length=period)
        if atr is None or atr.empty:
            return None
        return round(float(atr.dropna().iloc[-1]), 2)
    except Exception as e:
        logger.error(f"ATR error: {e}")
        return None


def compute_all(df: pd.DataFrame, rsi_period: int = 14) -> dict:
    """Compute all indicators for a given OHLCV dataframe."""
    return {
        "RSI": compute_rsi(df, rsi_period),
        "SMA_20": compute_sma(df, 20),
        "SMA_50": compute_sma(df, 50),
        "EMA_20": compute_ema(df, 20),
        "volume_ratio": compute_volume_ratio(df),
        "ATR": compute_atr(df),
        **compute_macd(df),
    }
