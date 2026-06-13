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
from data.stock_info import get_bulk_info
from data.persistence import (
    save_screen_result, load_screen_result,
    load_custom_watchlists, save_custom_watchlists,
    add_symbol_to_watchlist, remove_symbol_from_watchlist,
    create_watchlist, delete_watchlist,
)
from analysis.screener import screen_symbol, apply_filters, check_rules_for_symbol
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

# ══════════════════════════════════════════════════════════════════════════════
# PROFESSIONAL CSS
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("""
<style>
/* ── Global ── */
[data-testid="stAppViewContainer"] { background: #0e1117; }
[data-testid="stSidebar"] { background: #161b27 !important; border-right: 1px solid #2d3748; }
[data-testid="stSidebar"] * { color: #e2e8f0 !important; }

/* ── Metric Cards ── */
.metric-card {
    background: linear-gradient(135deg, #1a2234 0%, #1e2d40 100%);
    border: 1px solid #2d3748;
    border-radius: 12px;
    padding: 16px 20px;
    text-align: center;
    transition: transform .15s;
}
.metric-card:hover { transform: translateY(-2px); border-color: #4a9eff; }
.metric-card .label { font-size: 12px; color: #94a3b8; font-weight: 500; letter-spacing: .5px; text-transform: uppercase; margin-bottom: 6px; }
.metric-card .value { font-size: 28px; font-weight: 700; line-height: 1; }
.metric-card .sub   { font-size: 11px; color: #64748b; margin-top: 4px; }
.metric-green .value { color: #22c55e; }
.metric-red   .value { color: #ef4444; }
.metric-orange.value { color: #f97316; }
.metric-blue  .value { color: #3b82f6; }
.metric-purple.value { color: #a855f7; }

/* ── Page Title ── */
.page-title { font-size: 24px; font-weight: 700; color: #f1f5f9; margin: 0; }
.page-sub   { font-size: 13px; color: #64748b; margin-top: 2px; }

/* ── Filter Tabs ── */
.filter-tab-active {
    background: #1d4ed8 !important; color: white !important;
    border-radius: 8px; padding: 4px 14px; font-size: 13px; font-weight: 600;
}

/* ── Table ── */
[data-testid="stDataFrame"] { border-radius: 10px; overflow: hidden; }
thead th { background: #1e293b !important; color: #94a3b8 !important; font-size: 12px !important; text-transform: uppercase; }

/* ── Sidebar section headers ── */
.sidebar-section { font-size: 11px; font-weight: 700; color: #64748b; text-transform: uppercase;
    letter-spacing: 1px; padding: 8px 0 4px; border-bottom: 1px solid #2d3748; margin-bottom: 8px; }

/* ── Badge ── */
.badge { display:inline-block; padding:2px 8px; border-radius:999px; font-size:11px; font-weight:600; }
.badge-green  { background:#14532d; color:#4ade80; }
.badge-red    { background:#450a0a; color:#f87171; }
.badge-orange { background:#431407; color:#fb923c; }
.badge-blue   { background:#1e3a5f; color:#60a5fa; }

/* ── Refresh banner ── */
.cache-banner {
    background: #1e293b; border: 1px solid #334155; border-radius: 8px;
    padding: 8px 14px; font-size: 12px; color: #94a3b8; margin-bottom: 12px;
}
</style>
""", unsafe_allow_html=True)

# ── Session state ─────────────────────────────────────────────────────────────
for _k, _v in [("last_refresh", None), ("df_screen", None), ("saved_at", None),
               ("rules", [dict(r) for r in NOTIFICATION_RULES]),
               ("current_watchlist", DEFAULT_WATCHLIST),
               ("custom_wl", None), ("timeframe", "Daily")]:
    if _k not in st.session_state:
        st.session_state[_k] = _v


# ── Helpers ───────────────────────────────────────────────────────────────────
@st.cache_data(ttl=86400, show_spinner="Fetching index from NSE...")
def get_symbols(watchlist_name: str) -> list:
    custom = load_custom_watchlists()
    if watchlist_name in custom:
        return custom[watchlist_name]
    if watchlist_name in NSE_DYNAMIC_INDICES:
        syms = fetch_index_symbols(watchlist_name)
        return syms if syms else []
    return []


def _all_watchlist_names() -> list:
    custom = load_custom_watchlists()
    return NSE_DYNAMIC_INDICES + list(custom.keys())


def _metric_card(label: str, value, sub: str = "", color: str = "blue") -> str:
    return f"""<div class="metric-card metric-{color}">
        <div class="label">{label}</div>
        <div class="value">{value}</div>
        <div class="sub">{sub}</div>
    </div>"""


def _fmt_rsi(val) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return "—"
    v = float(val)
    if v >= 70:
        return f'<span class="badge badge-red">{v:.0f}</span>'
    if v <= 30:
        return f'<span class="badge badge-green">{v:.0f}</span>'
    return f"{v:.0f}"

# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown(f"## {APP_ICON} {APP_TITLE}")
    st.markdown('<div class="sidebar-section">Market & Index</div>', unsafe_allow_html=True)

    market      = st.selectbox("Market", list(MARKETS.keys()), index=0, label_visibility="collapsed")
    currency    = MARKETS[market]["currency"]
    all_wl      = _all_watchlist_names()
    default_idx = all_wl.index(DEFAULT_WATCHLIST) if DEFAULT_WATCHLIST in all_wl else 0
    watchlist_name = st.selectbox("Watchlist / Index", all_wl, index=default_idx)

    if watchlist_name != st.session_state.current_watchlist:
        st.session_state.current_watchlist = watchlist_name
        st.session_state.df_screen = None
        st.session_state.saved_at  = None

    symbols  = get_symbols(watchlist_name)
    is_dyn   = watchlist_name in NSE_DYNAMIC_INDICES
    st.caption(f"{len(symbols)} stocks" + (" · NSE live, cached 24h" if is_dyn else " · custom list"))

    timeframe = st.selectbox("Timeframe", list(TIMEFRAMES.keys()))

    st.markdown('<div class="sidebar-section">Screener Filters</div>', unsafe_allow_html=True)
    rsi_min, rsi_max = st.slider("RSI Range", 0, 100, (0, 100))
    rsi_period = st.number_input("RSI Period", 2, 50, 14)
    vol_mult   = st.number_input("Min Vol Ratio (vs 20d avg)", 0.0, 10.0, 0.0, step=0.5, format="%.1f")
    pc_min     = st.number_input("Min Change%", value=-100.0, step=1.0, format="%.1f")
    pc_max     = st.number_input("Max Change%", value=100.0,  step=1.0, format="%.1f")

    st.divider()
    refresh_clicked = st.button("🔄 Refresh Live Data", use_container_width=True, type="primary")

    # Show cache status
    cached_df, cached_at = load_screen_result(watchlist_name, timeframe)
    if st.session_state.df_screen is None and cached_df is not None:
        st.session_state.df_screen = cached_df
        st.session_state.saved_at  = cached_at

    if st.session_state.saved_at:
        try:
            saved_dt  = datetime.fromisoformat(st.session_state.saved_at)
            mins_ago  = int((datetime.now() - saved_dt).total_seconds() / 60)
            age_str   = f"{mins_ago}m ago" if mins_ago < 60 else f"{mins_ago//60}h ago"
        except Exception:
            age_str = "unknown"
        st.markdown(f'<div class="cache-banner">📦 Showing saved data · {age_str}</div>', unsafe_allow_html=True)
    else:
        st.caption("No cached data — click Refresh")

    if not symbols:
        st.warning("⚠️ No symbols. Check NSE connection.")

# ══════════════════════════════════════════════════════════════════════════════
# LIVE REFRESH HANDLER
# ══════════════════════════════════════════════════════════════════════════════
if refresh_clicked and symbols:
    clear_cache()
    # Pre-fetch all stock info (name, sector, 52W high) in bulk
    ph_info = st.empty()
    ph_info.info(f"Fetching metadata for {len(symbols)} stocks…")
    info_map = get_bulk_info(symbols)
    ph_info.empty()

    progress_bar = st.progress(0, text=f"Screening {len(symbols)} stocks…")
    rows = []
    for i, sym in enumerate(symbols):
        try:
            row = screen_symbol(sym, timeframe=timeframe,
                                rsi_period=int(rsi_period), ttl=0,
                                stock_info=info_map.get(sym, {}))
            rows.append(row)
        except Exception:
            rows.append({"Symbol": sym, "Name": sym})
        progress_bar.progress((i + 1) / len(symbols),
                              text=f"Screening… {i+1}/{len(symbols)} — {sym}")
    progress_bar.empty()

    df_new = pd.DataFrame(rows)
    save_screen_result(watchlist_name, timeframe, df_new)
    st.session_state.df_screen = df_new
    st.session_state.saved_at  = datetime.now().isoformat()
    st.session_state.last_refresh = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# MAIN TABS
# ══════════════════════════════════════════════════════════════════════════════
tab1, tab2, tab3, tab4, tab5 = st.tabs(
    ["📊 Screener", "📈 Chart", "⭐ Watchlists", "🔔 Alerts", "⚙️ Settings"])

# ─────────────────────────────────────────────────────────────────────────────
# TAB 1: SCREENER
# ─────────────────────────────────────────────────────────────────────────────
with tab1:
    # ── Header row ──
    hcol1, hcol2 = st.columns([6, 2])
    with hcol1:
        st.markdown(f'<p class="page-title">{watchlist_name}</p>'
                    f'<p class="page-sub">{timeframe} timeframe · {len(symbols)} stocks</p>',
                    unsafe_allow_html=True)

    if st.session_state.df_screen is None:
        st.info("👈 Click **Refresh Live Data** in the sidebar to load market data.")
        if len(symbols) > 100:
            st.warning(f"⏱ {watchlist_name} has {len(symbols)} stocks. First load ≈ {len(symbols)//120 + 1}–{len(symbols)//80 + 1} min. Subsequent page loads use saved cache instantly.")
    else:
        df = st.session_state.df_screen.copy()

        # ── Compute stats ──
        g   = int((df["Change%"] > 0).sum())  if "Change%" in df.columns else 0
        lo  = int((df["Change%"] < 0).sum())  if "Change%" in df.columns else 0
        ob  = int((df.get("RSI", pd.Series()) >= 70).sum()) if "RSI" in df.columns else 0
        os_ = int((df.get("RSI", pd.Series()) <= 30).sum()) if "RSI" in df.columns else 0
        ma_all = int(df.get("above_sma20", pd.Series(False)).astype(bool).sum() &
                     df.get("above_sma50", pd.Series(False)).astype(bool).sum() &
                     df.get("above_sma200", pd.Series(False)).astype(bool).sum()) if "above_sma20" in df.columns else 0
        ath = int(df.get("Near 52W High", pd.Series(False)).astype(bool).sum()) if "Near 52W High" in df.columns else 0

        # ── Stats cards ──
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        cards = [
            (c1, "Gainers",        g,    "",          "green"),
            (c2, "Losers",         lo,   "",          "red"),
            (c3, "RSI Overbought", ob,   "RSI ≥ 70",  "red"),
            (c4, "RSI Oversold",   os_,  "RSI ≤ 30",  "green"),
            (c5, "Above All MAs",  ma_all,"20/50/200", "blue"),
            (c6, "Near 52W High",  ath,  "within 3%", "purple"),
        ]
        for col, label, val, sub, color in cards:
            with col:
                st.markdown(_metric_card(label, val, sub, color), unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        # ── Filter sub-tabs ──
        ft_all, ft_rsi, ft_ma, ft_52w = st.tabs(
            ["All Stocks", "🔴 RSI Overbought (D+W+M)", "📈 Above MAs", "🏔 Near 52W High"])

        def _style_df(df_in: pd.DataFrame, cur: str) -> pd.io.formats.style.Styler:
            cols_want = ["Name", "Sector", "Price", "Change%",
                         "RSI_D", "RSI_W", "RSI_M",
                         "above_sma20", "above_sma50", "above_sma200",
                         "volume_ratio", "Near 52W High"]
            cols_show = [c for c in cols_want if c in df_in.columns]
            display   = df_in[cols_show].copy()

            # Boolean → tick/cross
            for bc in ["above_sma20", "above_sma50", "above_sma200", "Near 52W High"]:
                if bc in display.columns:
                    display[bc] = display[bc].apply(lambda x: "✅" if x else "")

            def _chg(v):
                if pd.isna(v): return ""
                return "color:#22c55e;font-weight:700" if v > 0 else "color:#ef4444;font-weight:700"
            def _rsi(v):
                if pd.isna(v): return ""
                if v >= 70: return "background-color:#450a0a;color:#f87171;font-weight:700"
                if v <= 30: return "background-color:#14532d;color:#4ade80;font-weight:700"
                return ""

            fmt = {"Price": lambda x: f"{cur}{x:,.2f}" if pd.notna(x) else "—",
                   "Change%":    lambda x: f"{x:+.2f}%" if pd.notna(x) else "—",
                   "volume_ratio": lambda x: f"{x:.2f}x" if pd.notna(x) else "—"}
            for rc in ["RSI_D","RSI_W","RSI_M"]:
                if rc in display.columns:
                    fmt[rc] = lambda x: f"{x:.1f}" if pd.notna(x) else "—"

            rsi_cols = [c for c in ["RSI_D","RSI_W","RSI_M"] if c in display.columns]
            styled = display.style.format(fmt, na_rep="—")
            if "Change%" in display.columns:
                styled = styled.map(_chg, subset=["Change%"])
            if rsi_cols:
                styled = styled.map(_rsi, subset=rsi_cols)
            return styled

        def _apply_sidebar_filters(df_in):
            return apply_filters(df_in, rsi_min=rsi_min, rsi_max=rsi_max,
                                 volume_multiplier=vol_mult,
                                 price_change_min=pc_min, price_change_max=pc_max)

        with ft_all:
            df_f = _apply_sidebar_filters(df)
            st.caption(f"**{len(df_f)}** of {len(df)} stocks")
            st.dataframe(_style_df(df_f, currency), use_container_width=True,
                         hide_index=True, height=520)

        with ft_rsi:
            st.caption("Stocks with RSI > 70 on ALL three timeframes (Daily + Weekly + Monthly)")
            df_rsi = df.copy()
            for rc in ["RSI_D","RSI_W","RSI_M"]:
                if rc in df_rsi.columns:
                    df_rsi = df_rsi[df_rsi[rc].notna() & (df_rsi[rc] >= 70)]
            st.caption(f"**{len(df_rsi)}** stocks")
            if df_rsi.empty:
                st.info("No stocks with RSI ≥ 70 across all three timeframes right now.")
            else:
                st.dataframe(_style_df(df_rsi, currency), use_container_width=True,
                             hide_index=True, height=400)

        with ft_ma:
            st.caption("Stocks trading above SMA 20, SMA 50, and SMA 200 simultaneously")
            df_ma = df.copy()
            for col_flag in ["above_sma20","above_sma50","above_sma200"]:
                if col_flag in df_ma.columns:
                    df_ma = df_ma[df_ma[col_flag] == True]
            st.caption(f"**{len(df_ma)}** stocks above all three MAs")
            if df_ma.empty:
                st.info("No stocks trading above all three moving averages right now.")
            else:
                st.dataframe(_style_df(df_ma, currency), use_container_width=True,
                             hide_index=True, height=400)

        with ft_52w:
            st.caption("Stocks within 3% of their 52-week high")
            df_52 = df[df.get("Near 52W High", pd.Series(False)).astype(bool)] if "Near 52W High" in df.columns else df.iloc[0:0]
            st.caption(f"**{len(df_52)}** stocks near 52-week high")
            if df_52.empty:
                st.info("No stocks near 52-week highs. Try refreshing to get latest data.")
            else:
                st.dataframe(_style_df(df_52, currency), use_container_width=True,
                             hide_index=True, height=400)

# ─────────────────────────────────────────────────────────────────────────────
# TAB 2: CHART
# ─────────────────────────────────────────────────────────────────────────────
with tab2:
    st.markdown('<p class="page-title">📈 Price Chart</p>', unsafe_allow_html=True)

    chart_options = symbols if symbols else ["RELIANCE.NS"]
    c1, c2, c3 = st.columns([3, 1, 1])
    with c1:
        chart_symbol = st.selectbox("Symbol", chart_options, key="chart_sym")
    with c2:
        chart_tf = st.selectbox("Timeframe", list(TIMEFRAMES.keys()), key="chart_tf")
    with c3:
        show_200 = st.checkbox("SMA 200", value=True, key="show_200")

    if st.button("📊 Load Chart", key="chart_btn", type="primary"):
        tf_cfg = TIMEFRAMES[chart_tf]
        # For SMA200 we need more history
        period = "5y" if show_200 else tf_cfg["period"]
        with st.spinner(f"Loading {chart_symbol}…"):
            df_chart = fetch_ohlcv(chart_symbol, period=period, interval=tf_cfg["interval"])

        if df_chart is not None and not df_chart.empty:
            fig = go.Figure()
            fig.add_trace(go.Candlestick(
                x=df_chart.index, open=df_chart["Open"], high=df_chart["High"],
                low=df_chart["Low"], close=df_chart["Close"], name=chart_symbol,
                increasing_line_color="#22c55e", decreasing_line_color="#ef4444"))
            for period_n, color, dash in [(20,"#f97316","solid"),(50,"#3b82f6","solid"),(200,"#a855f7","dash")]:
                if len(df_chart) >= period_n and (period_n < 200 or show_200):
                    fig.add_trace(go.Scatter(
                        x=df_chart.index, y=df_chart["Close"].rolling(period_n).mean(),
                        line=dict(color=color, width=1, dash=dash), name=f"SMA {period_n}"))
            fig.update_layout(
                title=dict(text=chart_symbol, font=dict(size=16, color="#f1f5f9")),
                xaxis_rangeslider_visible=False, height=520, template="plotly_dark",
                paper_bgcolor="#0e1117", plot_bgcolor="#0e1117",
                yaxis_title=f"Price ({currency})", margin=dict(l=0,r=0,t=40,b=0))
            st.plotly_chart(fig, use_container_width=True)

            fig_vol = go.Figure(go.Bar(x=df_chart.index, y=df_chart["Volume"],
                                       marker_color="#3b82f6", opacity=0.7))
            fig_vol.update_layout(height=160, template="plotly_dark",
                                   paper_bgcolor="#0e1117", plot_bgcolor="#0e1117",
                                   showlegend=False, margin=dict(l=0,r=0,t=10,b=0))
            st.plotly_chart(fig_vol, use_container_width=True)
        else:
            st.error(f"No data for {chart_symbol}")

# ─────────────────────────────────────────────────────────────────────────────
# TAB 3: WATCHLIST MANAGER
# ─────────────────────────────────────────────────────────────────────────────
with tab3:
    st.markdown('<p class="page-title">⭐ Watchlist Manager</p>', unsafe_allow_html=True)
    custom_wl = load_custom_watchlists()

    wl_col, detail_col = st.columns([1, 2])

    with wl_col:
        st.subheader("My Watchlists")
        selected_wl = st.radio("Select", list(custom_wl.keys()), key="wl_radio")

        with st.form("new_wl_form"):
            new_wl_name = st.text_input("New watchlist name")
            if st.form_submit_button("➕ Create"):
                if new_wl_name:
                    create_watchlist(new_wl_name)
                    get_symbols.clear()
                    st.success(f"Created '{new_wl_name}'")
                    st.rerun()

        if selected_wl and st.button(f"🗑 Delete '{selected_wl}'", key="del_wl"):
            delete_watchlist(selected_wl)
            get_symbols.clear()
            st.warning(f"Deleted '{selected_wl}'")
            st.rerun()

    with detail_col:
        if selected_wl:
            st.subheader(f"📋 {selected_wl}")
            wl_syms = custom_wl.get(selected_wl, [])
            st.caption(f"{len(wl_syms)} stocks")

            # Add stock
            with st.form("add_sym_form"):
                ac1, ac2 = st.columns([3,1])
                with ac1:
                    add_sym = st.text_input("Add symbol (e.g. RELIANCE.NS)", placeholder="SYMBOL.NS")
                with ac2:
                    st.markdown("<br>", unsafe_allow_html=True)
                    add_submitted = st.form_submit_button("Add ➕")
                if add_submitted and add_sym:
                    sym_clean = add_sym.strip().upper()
                    add_symbol_to_watchlist(selected_wl, sym_clean)
                    get_symbols.clear()
                    st.success(f"Added {sym_clean}")
                    st.rerun()

            # Show & remove
            if wl_syms:
                for sym in wl_syms:
                    sc1, sc2 = st.columns([4,1])
                    with sc1:
                        st.write(sym)
                    with sc2:
                        if st.button("✕", key=f"rm_{selected_wl}_{sym}"):
                            remove_symbol_from_watchlist(selected_wl, sym)
                            get_symbols.clear()
                            st.rerun()
            else:
                st.info("Empty watchlist. Add stocks above.")

# ─────────────────────────────────────────────────────────────────────────────
# TAB 4: ALERTS
# ─────────────────────────────────────────────────────────────────────────────
with tab4:
    st.markdown('<p class="page-title">🔔 Alert Rules & WhatsApp</p>', unsafe_allow_html=True)
    wa_cfg = _get_wa_config()

    wa_status = "✅ Enabled" if wa_cfg.get("enabled") else "❌ Not configured"
    st.markdown(f'<div class="cache-banner">WhatsApp status: {wa_status} · Phone: {wa_cfg.get("phone","—")}</div>',
                unsafe_allow_html=True)

    st.subheader("Rules")
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
    with st.expander("➕ Add Custom Rule"):
        with st.form("add_rule_form"):
            rc1, rc2, rc3, rc4, rc5 = st.columns([3, 2, 1, 1, 1])
            with rc1: new_name  = st.text_input("Rule Name")
            with rc2: new_field = st.selectbox("Field", ["RSI","RSI_D","RSI_W","RSI_M","price_change_pct","volume_ratio","macd"])
            with rc3: new_op    = st.selectbox("Op",    [">","<",">=","<=","=="])
            with rc4: new_val   = st.number_input("Value", value=70.0, step=0.5)
            with rc5: new_tf    = st.selectbox("TF", list(TIMEFRAMES.keys()))
            if st.form_submit_button("Add") and new_name:
                st.session_state.rules.append({"name": new_name, "field": new_field,
                    "operator": new_op, "value": new_val, "timeframe": new_tf, "enabled": True})
                st.success(f"Added '{new_name}'")
                st.rerun()

    st.divider()
    st.subheader("🧪 Manual Test")
    c1, c2 = st.columns(2)
    with c1: test_wl = st.selectbox("Watchlist", _all_watchlist_names(), key="test_wl")
    with c2: send_wa = st.checkbox("Send WhatsApp on trigger", value=False)

    if st.button("▶ Run Alert Check", type="primary"):
        test_syms     = get_symbols(test_wl)
        enabled_rules = [r for r in st.session_state.rules if r.get("enabled")]
        if not enabled_rules:
            st.warning("No enabled rules.")
        elif not test_syms:
            st.error("Could not load symbols.")
        else:
            all_alerts, pb = [], st.progress(0)
            for idx, sym in enumerate(test_syms):
                all_alerts.extend(check_rules_for_symbol(sym, enabled_rules))
                pb.progress((idx+1)/len(test_syms))
            pb.empty()
            if all_alerts:
                st.success(f"✅ {len(all_alerts)} alert(s) triggered!")
                for a in all_alerts:
                    st.write(f"• **{a['symbol']}**: {a['rule']} — `{a['field']}={a['actual']}` (threshold {a['threshold']})")
                if send_wa and wa_cfg.get("enabled"):
                    ok = send_whatsapp(wa_cfg["phone"], wa_cfg["api_key"], format_alert_message(all_alerts))
                    st.success("📱 WhatsApp sent!" if ok else "❌ Send failed.")
            else:
                st.info("No alerts triggered.")

# ─────────────────────────────────────────────────────────────────────────────
# TAB 5: SETTINGS
# ─────────────────────────────────────────────────────────────────────────────
with tab5:
    st.markdown('<p class="page-title">⚙️ Settings</p>', unsafe_allow_html=True)
    wa_cfg = _get_wa_config()

    st.subheader("📱 WhatsApp Setup (CallMeBot — Free)")
    st.markdown("""
1. Save **+34 644 59 21 64** as "CallMeBot" in WhatsApp contacts
2. Send: `I allow callmebot to send me messages`
3. Receive API key in reply
4. Add to **Streamlit Cloud → App Settings → Secrets**:
```toml
[whatsapp]
enabled = true
phone = "+91YOURPHONE"
api_key = "YOURCALLMEBOTKEY"
notify_watchlist = "Nifty 50"
```
""")

    st.divider()
    st.subheader("🗂 NSE Index Cache")
    cache_info = get_cache_info()
    if cache_info:
        for k, v in cache_info.items():
            st.write(f"**{k}**: {v['count']} stocks — `{v['updated_at'][:19]}`")
    else:
        st.info("No index cache yet.")

    if st.button("🗑 Clear NSE Index Cache"):
        import os
        from data.nifty import CACHE_FILE
        if os.path.exists(CACHE_FILE): os.remove(CACHE_FILE)
        get_symbols.clear()
        st.success("Cleared. Next load re-fetches from NSE.")
        st.rerun()
