"""
Indian Market Dashboard - Main Streamlit App
Runs on: Streamlit Community Cloud (free) or self-hosted VM
"""

import logging
from datetime import datetime

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from config import (
    NSE_DYNAMIC_INDICES, STATIC_WATCHLISTS, DEFAULT_WATCHLIST,
    TIMEFRAMES, SCREENER_DEFAULTS, NOTIFICATION_RULES, WHATSAPP_CONFIG,
    MARKETS, DEFAULT_MARKET, APP_TITLE, APP_ICON, CACHE_TTL_SECONDS,
)
from data.fetcher import fetch_ohlcv, clear_cache
from data.nifty import fetch_index_symbols, get_cache_info
from analysis.screener import screen_watchlist, apply_filters, check_rules_for_symbol
from notifications.whatsapp import send_whatsapp, format_alert_message

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Read secrets: Streamlit Cloud secrets.toml OR config.py fallback ──────────
def _get_wa_config() -> dict:
    try:
        return {
            "enabled": st.secrets["whatsapp"]["enabled"],
            "phone": st.secrets["whatsapp"]["phone"],
            "api_key": st.secrets["whatsapp"]["api_key"],
            "notify_watchlist": st.secrets["whatsapp"].get("notify_watchlist", "Nifty 50"),
        }
    except Exception:
        return WHATSAPP_CONFIG


st.set_page_config(
    page_title=APP_TITLE,
    page_icon=APP_ICON,
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Session state defaults ────────────────────────────────────────────────────
if "last_refresh" not in st.session_state:
    st.session_state.last_refresh = None
if "df_screen" not in st.session_state:
    st.session_state.df_screen = None
if "rules" not in st.session_state:
    st.session_state.rules = [dict(r) for r in NOTIFICATION_RULES]
if "current_watchlist" not in st.session_state:
    st.session_state.current_watchlist = DEFAULT_WATCHLIST
if "symbols" not in st.session_state:
    st.session_state.symbols = []


# ── Helper: resolve symbols for the selected watchlist ───────────────────────
@st.cache_data(ttl=86400, show_spinner="Fetching index constituents from NSE...")
def get_symbols(watchlist_name: str) -> list:
    if watchlist_name in NSE_DYNAMIC_INDICES:
        syms = fetch_index_symbols(watchlist_name)
        return syms if syms else []
    return STATIC_WATCHLISTS.get(watchlist_name, [])


ALL_WATCHLIST_NAMES = NSE_DYNAMIC_INDICES + list(STATIC_WATCHLISTS.keys())

# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.title(f"{APP_ICON} {APP_TITLE}")
    st.divider()

    market = st.selectbox("Market", list(MARKETS.keys()),
                           index=list(MARKETS.keys()).index(DEFAULT_MARKET))
    currency = MARKETS[market]["currency"]

    default_idx = ALL_WATCHLIST_NAMES.index(DEFAULT_WATCHLIST) if DEFAULT_WATCHLIST in ALL_WATCHLIST_NAMES else 0
    watchlist_name = st.selectbox("Watchlist / Index", ALL_WATCHLIST_NAMES, index=default_idx)

    # Load symbols (cached from NSE or static list)
    if watchlist_name != st.session_state.current_watchlist:
        st.session_state.current_watchlist = watchlist_name
        st.session_state.df_screen = None  # clear stale data when switching
        st.session_state.last_refresh = None

    symbols = get_symbols(watchlist_name)
    st.caption(f"{len(symbols)} symbols" + (" (live from NSE, cached 24h)" if watchlist_name in NSE_DYNAMIC_INDICES else ""))

    timeframe = st.selectbox("Timeframe", list(TIMEFRAMES.keys()))

    st.divider()
    st.subheader("🔍 Screener Filters")

    rsi_min, rsi_max = st.slider("RSI Range", 0, 100,
                                  (int(SCREENER_DEFAULTS["rsi_min"]),
                                   int(SCREENER_DEFAULTS["rsi_max"])))
    rsi_period = st.number_input("RSI Period", min_value=2, max_value=50,
                                  value=SCREENER_DEFAULTS["rsi_period"])
    vol_mult = st.number_input("Min Volume Ratio (vs 20d avg)", min_value=0.0,
                                max_value=10.0, value=1.0, step=0.1, format="%.1f")
    pc_min = st.number_input("Price Change % Min", value=-100.0, step=0.5, format="%.1f")
    pc_max = st.number_input("Price Change % Max", value=100.0, step=0.5, format="%.1f")

    st.divider()
    refresh_clicked = st.button("🔄 Refresh Data", use_container_width=True, type="primary")

    if st.session_state.last_refresh:
        st.caption(f"Last refresh: {st.session_state.last_refresh}")
    else:
        st.caption("Not loaded yet — click Refresh")

    if not symbols:
        st.warning("⚠️ No symbols loaded. Check internet / NSE access.")

# ══════════════════════════════════════════════════════════════════════════════
# DATA LOAD ON REFRESH  (batched with live progress for large indices)
# ══════════════════════════════════════════════════════════════════════════════
if refresh_clicked and symbols:
    clear_cache()
    progress_bar = st.progress(0, text=f"Loading {len(symbols)} symbols...")
    rows = []
    from analysis.screener import screen_symbol
    for i, sym in enumerate(symbols):
        try:
            row = screen_symbol(sym, timeframe=timeframe, rsi_period=int(rsi_period), ttl=0)
            rows.append(row)
        except Exception:
            rows.append({"Symbol": sym})
        pct = (i + 1) / len(symbols)
        progress_bar.progress(pct, text=f"Loading… {i+1}/{len(symbols)} — {sym}")
    progress_bar.empty()
    st.session_state.df_screen = pd.DataFrame(rows)
    st.session_state.last_refresh = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# MAIN TABS
# ══════════════════════════════════════════════════════════════════════════════
tab1, tab2, tab3, tab4 = st.tabs(["📊 Screener", "📈 Chart", "🔔 Alerts", "⚙️ Settings"])

# ─────────────────────────────────────────────────────────────────────────────
# TAB 1: SCREENER TABLE
# ─────────────────────────────────────────────────────────────────────────────
with tab1:
    st.header(f"📊 {watchlist_name} — {timeframe}")

    if st.session_state.df_screen is None:
        st.info("👈 Click **Refresh Data** in the sidebar to load latest market data.")
        if watchlist_name == "Nifty 500":
            st.warning("⏱ Nifty 500 has ~500 stocks. First load takes ~3-4 minutes. Subsequent refreshes use cache.")
    else:
        df = st.session_state.df_screen.copy()
        df_filtered = apply_filters(
            df,
            rsi_min=rsi_min,
            rsi_max=rsi_max,
            volume_multiplier=vol_mult if vol_mult > 0 else 0,
            price_change_min=pc_min,
            price_change_max=pc_max,
        )

        st.caption(f"Showing **{len(df_filtered)}** of {len(df)} symbols after filters.")

        display_cols = ["Symbol", "Price", "Change%", "RSI", "volume_ratio",
                        "SMA_20", "SMA_50", "EMA_20", "Volume"]
        display_cols = [c for c in display_cols if c in df_filtered.columns]

        def color_change(val):
            if val is None or pd.isna(val):
                return ""
            return "color: green; font-weight:bold" if val > 0 else "color: red; font-weight:bold" if val < 0 else ""

        def color_rsi(val):
            if val is None or pd.isna(val):
                return ""
            if val >= 70:
                return "background-color: #ffcccc"
            elif val <= 30:
                return "background-color: #ccffcc"
            return ""

        styled = (
            df_filtered[display_cols]
            .style
            .format({
                "Price": lambda x: f"{currency}{x:.2f}" if pd.notna(x) else "—",
                "Change%": lambda x: f"{x:+.2f}%" if pd.notna(x) else "—",
                "RSI": lambda x: f"{x:.1f}" if pd.notna(x) else "—",
                "volume_ratio": lambda x: f"{x:.2f}x" if pd.notna(x) else "—",
                "SMA_20": lambda x: f"{currency}{x:.2f}" if pd.notna(x) else "—",
                "SMA_50": lambda x: f"{currency}{x:.2f}" if pd.notna(x) else "—",
                "EMA_20": lambda x: f"{currency}{x:.2f}" if pd.notna(x) else "—",
                "Volume": lambda x: f"{int(x):,}" if pd.notna(x) else "—",
            })
            .map(color_change, subset=["Change%"])
            .map(color_rsi, subset=["RSI"] if "RSI" in display_cols else [])
        )

        st.dataframe(styled, use_container_width=True, height=550)

        st.divider()
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            gainers = int((df_filtered.get("Change%", pd.Series()) > 0).sum()) if "Change%" in df_filtered else 0
            st.metric("Gainers 📈", gainers)
        with col2:
            losers = int((df_filtered.get("Change%", pd.Series()) < 0).sum()) if "Change%" in df_filtered else 0
            st.metric("Losers 📉", losers)
        with col3:
            overbought = int((df_filtered.get("RSI", pd.Series()) >= 70).sum()) if "RSI" in df_filtered else 0
            st.metric("RSI ≥ 70 🔴", overbought)
        with col4:
            oversold = int((df_filtered.get("RSI", pd.Series()) <= 30).sum()) if "RSI" in df_filtered else 0
            st.metric("RSI ≤ 30 🟢", oversold)

# ─────────────────────────────────────────────────────────────────────────────
# TAB 2: CANDLESTICK CHART
# ─────────────────────────────────────────────────────────────────────────────
with tab2:
    st.header("📈 Price Chart")

    chart_options = symbols if symbols else ["RELIANCE.NS"]
    col1, col2 = st.columns([2, 1])
    with col1:
        chart_symbol = st.selectbox("Select Symbol", chart_options, key="chart_sym")
    with col2:
        chart_tf = st.selectbox("Timeframe", list(TIMEFRAMES.keys()), key="chart_tf")

    if st.button("Load Chart", key="chart_btn"):
        tf_cfg = TIMEFRAMES[chart_tf]
        with st.spinner(f"Loading chart for {chart_symbol}..."):
            df_chart = fetch_ohlcv(chart_symbol, period=tf_cfg["period"], interval=tf_cfg["interval"])

        if df_chart is not None and not df_chart.empty:
            fig = go.Figure()
            fig.add_trace(go.Candlestick(
                x=df_chart.index,
                open=df_chart["Open"], high=df_chart["High"],
                low=df_chart["Low"], close=df_chart["Close"],
                name=chart_symbol,
            ))
            if len(df_chart) >= 20:
                fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart["Close"].rolling(20).mean(),
                                          line=dict(color="orange", width=1), name="SMA 20"))
            if len(df_chart) >= 50:
                fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart["Close"].rolling(50).mean(),
                                          line=dict(color="royalblue", width=1), name="SMA 50"))
            fig.update_layout(
                title=f"{chart_symbol} — {chart_tf}",
                xaxis_title="Date", yaxis_title=f"Price ({currency})",
                xaxis_rangeslider_visible=False, height=500, template="plotly_dark",
            )
            st.plotly_chart(fig, use_container_width=True)

            fig_vol = go.Figure(go.Bar(x=df_chart.index, y=df_chart["Volume"],
                                        marker_color="steelblue", name="Volume"))
            fig_vol.update_layout(title="Volume", height=200, template="plotly_dark", showlegend=False)
            st.plotly_chart(fig_vol, use_container_width=True)
        else:
            st.error(f"No data found for {chart_symbol}")

# ─────────────────────────────────────────────────────────────────────────────
# TAB 3: ALERT RULES & NOTIFICATIONS
# ─────────────────────────────────────────────────────────────────────────────
with tab3:
    st.header("🔔 Alert Rules & WhatsApp Notifications")
    wa_cfg = _get_wa_config()

    st.subheader("Active Rules")
    updated_rules = []
    for i, rule in enumerate(st.session_state.rules):
        col1, col2 = st.columns([5, 1])
        with col1:
            st.write(f"**{rule['name']}** — `{rule['field']} {rule['operator']} {rule['value']}` ({rule['timeframe']})")
        with col2:
            enabled = st.toggle("On", value=rule["enabled"], key=f"rule_{i}")
        rule["enabled"] = enabled
        updated_rules.append(rule)
    st.session_state.rules = updated_rules

    st.divider()
    st.subheader("➕ Add Custom Rule")
    with st.form("add_rule_form"):
        rc1, rc2, rc3, rc4, rc5 = st.columns([3, 2, 1, 1, 1])
        with rc1:
            new_name = st.text_input("Rule Name", placeholder="e.g. RSI Weekly Overbought")
        with rc2:
            new_field = st.selectbox("Field", ["RSI", "price_change_pct", "volume_ratio", "macd", "signal"])
        with rc3:
            new_op = st.selectbox("Operator", [">", "<", ">=", "<=", "=="])
        with rc4:
            new_val = st.number_input("Value", value=70.0, step=0.5)
        with rc5:
            new_tf = st.selectbox("Timeframe", list(TIMEFRAMES.keys()))
        if st.form_submit_button("Add Rule") and new_name:
            st.session_state.rules.append({
                "name": new_name, "field": new_field, "operator": new_op,
                "value": new_val, "timeframe": new_tf, "enabled": True,
            })
            st.success(f"Rule '{new_name}' added!")
            st.rerun()

    st.divider()
    st.subheader("🧪 Manual Alert Test")
    col1, col2 = st.columns(2)
    with col1:
        test_wl = st.selectbox("Test Watchlist", ALL_WATCHLIST_NAMES, key="test_wl")
    with col2:
        send_wa = st.checkbox("Send WhatsApp if alerts found", value=False)

    if st.button("▶ Run Check Now", key="run_check"):
        test_symbols = get_symbols(test_wl)
        enabled_rules = [r for r in st.session_state.rules if r.get("enabled")]
        if not enabled_rules:
            st.warning("No enabled rules.")
        elif not test_symbols:
            st.error("Could not load symbols for this watchlist.")
        else:
            all_alerts = []
            progress = st.progress(0)
            for idx, sym in enumerate(test_symbols):
                alerts = check_rules_for_symbol(sym, enabled_rules)
                all_alerts.extend(alerts)
                progress.progress((idx + 1) / len(test_symbols))
            progress.empty()

            if all_alerts:
                st.success(f"✅ {len(all_alerts)} alert(s) triggered!")
                for a in all_alerts:
                    st.write(f"• **{a['symbol']}**: {a['rule']} — `{a['field']}={a['actual']}` (threshold {a['threshold']})")
                if send_wa:
                    if wa_cfg.get("enabled"):
                        msg = format_alert_message(all_alerts)
                        ok = send_whatsapp(wa_cfg["phone"], wa_cfg["api_key"], msg)
                        st.success("📱 WhatsApp sent!" if ok else "❌ WhatsApp send failed.")
                    else:
                        st.warning("WhatsApp not configured. See Settings tab.")
            else:
                st.info("No alerts triggered for current rules.")

# ─────────────────────────────────────────────────────────────────────────────
# TAB 4: SETTINGS
# ─────────────────────────────────────────────────────────────────────────────
with tab4:
    st.header("⚙️ Settings")
    wa_cfg = _get_wa_config()

    st.subheader("📱 WhatsApp Setup (Free via CallMeBot)")
    st.markdown("""
**One-time setup (5 minutes):**
1. Save **+34 644 59 21 64** as "CallMeBot" in your phone contacts
2. Send WhatsApp message to that number: `I allow callmebot to send me messages`
3. You'll receive an **API key** in reply
4. Add to `.streamlit/secrets.toml` (Streamlit Cloud) or `config.py` (local):
   ```toml
   [whatsapp]
   enabled = true
   phone = "+91XXXXXXXXXX"
   api_key = "YOUR_KEY"
   notify_watchlist = "Nifty 50"
   ```
""")

    st.divider()
    st.subheader("� NSE Index Cache Status")
    cache_info = get_cache_info()
    if cache_info:
        for idx_name, info in cache_info.items():
            st.write(f"**{idx_name}**: {info['count']} symbols — last updated `{info['updated_at'][:19]}`")
    else:
        st.info("No index data cached yet. Select a dynamic index and click Refresh.")

    if st.button("🗑 Clear NSE Index Cache (force re-fetch from NSE)"):
        import os
        from data.nifty import CACHE_FILE
        if os.path.exists(CACHE_FILE):
            os.remove(CACHE_FILE)
        get_symbols.clear()
        st.success("Cache cleared. Next Refresh will re-fetch from NSE.")
        st.rerun()

    st.divider()
    st.subheader("📋 Config Summary")
    st.json({
        "whatsapp_enabled": wa_cfg.get("enabled"),
        "whatsapp_phone": wa_cfg.get("phone"),
        "notify_watchlist": wa_cfg.get("notify_watchlist"),
        "active_rules": sum(1 for r in st.session_state.rules if r["enabled"]),
        "total_rules": len(st.session_state.rules),
        "dynamic_indices": NSE_DYNAMIC_INDICES,
        "static_watchlists": list(STATIC_WATCHLISTS.keys()),
        "cache_ttl_seconds": CACHE_TTL_SECONDS,
    })
