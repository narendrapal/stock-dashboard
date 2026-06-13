"""
Central configuration for the Indian Market Dashboard.
Edit this file to customize stocks, rules, and notification settings.
"""

# ── Watchlists ────────────────────────────────────────────────────────────────
# NSE_DYNAMIC indices are fetched live from NSE website (cached 24h).
# Static lists are used for custom/personal watchlists.

NSE_DYNAMIC_INDICES = [
    "Nifty 500",
    "Nifty 50",
    "Nifty Next 50",
    "Nifty Midcap 150",
    "Nifty Smallcap 250",
    "Nifty Bank",
    "Nifty IT",
]

STATIC_WATCHLISTS = {
    "My Watchlist": [
        "RELIANCE.NS", "TCS.NS", "INFY.NS", "SBIN.NS", "HDFCBANK.NS",
        "ICICIBANK.NS", "AXISBANK.NS", "TATAMOTORS.NS", "WIPRO.NS", "BAJFINANCE.NS",
    ],
}

DEFAULT_WATCHLIST = "Nifty 500"

# ── Screener Filters (defaults shown in UI) ───────────────────────────────────
SCREENER_DEFAULTS = {
    "rsi_min": 0,
    "rsi_max": 100,
    "rsi_period": 14,
    "volume_multiplier": 1.0,   # volume > X * 20-day avg volume
    "price_change_min": -100.0, # % daily change min
    "price_change_max": 100.0,  # % daily change max
}

# ── Timeframes for multi-timeframe RSI ───────────────────────────────────────
TIMEFRAMES = {
    "Daily":   {"period": "3mo",  "interval": "1d"},
    "Weekly":  {"period": "1y",   "interval": "1wk"},
    "Monthly": {"period": "5y",   "interval": "1mo"},
}

# ── Notification Rules ────────────────────────────────────────────────────────
# Each rule: {name, condition_field, operator, value, timeframe, enabled}
# Operators: >, <, >=, <=, ==
NOTIFICATION_RULES = [
    {
        "name": "RSI Overbought (Daily)",
        "field": "RSI",
        "operator": ">",
        "value": 70,
        "timeframe": "Daily",
        "enabled": True,
    },
    {
        "name": "RSI Oversold (Daily)",
        "field": "RSI",
        "operator": "<",
        "value": 30,
        "timeframe": "Daily",
        "enabled": True,
    },
    {
        "name": "Volume Spike (2x avg)",
        "field": "volume_ratio",
        "operator": ">",
        "value": 2.0,
        "timeframe": "Daily",
        "enabled": True,
    },
    {
        "name": "Price Up > 3%",
        "field": "price_change_pct",
        "operator": ">",
        "value": 3.0,
        "timeframe": "Daily",
        "enabled": False,
    },
    {
        "name": "Price Down > 3%",
        "field": "price_change_pct",
        "operator": "<",
        "value": -3.0,
        "timeframe": "Daily",
        "enabled": False,
    },
]

# ── WhatsApp Notification (CallMeBot - FREE) ──────────────────────────────────
# Setup: Send "I allow callmebot to send me messages" to +34 644 59 21 64 on WhatsApp
# You'll get an API key back. Fill in below.
WHATSAPP_CONFIG = {
    "enabled": False,           # Set True after setup
    "phone": "+91XXXXXXXXXX",   # Your WhatsApp number with country code
    "api_key": "YOUR_API_KEY",  # Key received from CallMeBot
    "cron_interval_minutes": 30, # How often to run rule checks
    "notify_watchlist": "My Watchlist",  # Which watchlist to scan for alerts
}

# ── Market Config (extensible for global markets) ─────────────────────────────
MARKETS = {
    "India (NSE)": {"suffix": ".NS", "currency": "₹", "exchange": "NSE"},
    "India (BSE)": {"suffix": ".BO", "currency": "₹", "exchange": "BSE"},
    # Future:
    # "USA (NASDAQ)": {"suffix": "", "currency": "$", "exchange": "NASDAQ"},
    # "USA (NYSE)":   {"suffix": "", "currency": "$", "exchange": "NYSE"},
}

DEFAULT_MARKET = "India (NSE)"

# ── App Settings ──────────────────────────────────────────────────────────────
APP_TITLE = "Indian Market Screener"
APP_ICON = "📈"
CACHE_TTL_SECONDS = 300  # 5 min cache per stock data fetch
