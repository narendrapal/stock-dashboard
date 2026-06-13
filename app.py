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
/* ── Metric Cards ── */
.metric-card {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
    padding: 14px 16px;
    text-align: center;
    box-shadow: 0 1px 4px rgba(0,0,0,0.07);
    transition: transform .15s, box-shadow .15s;
}
.metric-card:hover { transform: translateY(-2px); box-shadow: 0 4px 14px rgba(0,0,0,0.12); }
.metric-card .label { font-size: 10px; color: #64748b; font-weight: 700; letter-spacing: .6px; text-transform: uppercase; margin-bottom: 6px; }
.metric-card .value { font-size: 30px; font-weight: 800; line-height: 1; }
.metric-card .sub   { font-size: 10px; color: #94a3b8; margin-top: 4px; }
.metric-green .value { color: #16a34a; }
.metric-red   .value { color: #dc2626; }
.metric-orange .value { color: #ea580c; }
.metric-blue  .value { color: #2563eb; }
.metric-purple .value { color: #7c3aed; }

/* ── Page Title ── */
.page-title { font-size: 22px; font-weight: 700; color: #1e293b; margin: 0; }
.page-sub   { font-size: 13px; color: #64748b; margin-top: 2px; }

/* ── Sidebar section headers ── */
.sidebar-section { font-size: 11px; font-weight: 700; color: #94a3b8; text-transform: uppercase;
    letter-spacing: 1px; padding: 8px 0 4px; border-bottom: 1px solid #e2e8f0; margin-bottom: 8px; }

/* ── Badge ── */
.badge { display:inline-block; padding:2px 8px; border-radius:999px; font-size:11px; font-weight:600; }
.badge-green  { background:#dcfce7; color:#15803d; }
.badge-red    { background:#fee2e2; color:#b91c1c; }
.badge-orange { background:#ffedd5; color:#c2410c; }
.badge-blue   { background:#dbeafe; color:#1d4ed8; }

/* ── Cache / info banner ── */
.cache-banner {
    background: #f0f9ff; border: 1px solid #bae6fd; border-radius: 8px;
    padding: 8px 14px; font-size: 12px; color: #0369a1; margin-bottom: 4px;
}
.warn-banner {
    background: #fffbeb; border: 1px solid #fde68a; border-radius: 8px;
    padding: 8px 14px; font-size: 12px; color: #92400e; margin-bottom: 4px;
}

/* ── Refresh timestamp ── */
.refresh-ts { font-size: 11px; color: #64748b; text-align: right; margin-top: 2px; }
</style>
""", unsafe_allow_html=True)

# ── Session state ─────────────────────────────────────────────────────────────
from datetime import timezone, timedelta
IST = timezone(timedelta(hours=5, minutes=30))

for _k, _v in [("last_refresh", None), ("df_screen", None), ("saved_at", None),
               ("rules", [dict(r) for r in NOTIFICATION_RULES]),
               ("current_watchlist", DEFAULT_WATCHLIST),
               ("refresh_requested", False),
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

    # Load cache on first visit (refresh button now lives in main area)
    cached_df, cached_at = load_screen_result(watchlist_name, timeframe)
    if st.session_state.df_screen is None and cached_df is not None:
        st.session_state.df_screen = cached_df
        st.session_state.saved_at  = cached_at

    if st.session_state.saved_at:
        try:
            saved_dt = datetime.fromisoformat(st.session_state.saved_at).astimezone(IST)
            age_secs = (datetime.now(IST) - saved_dt).total_seconds()
            age_str  = f"{int(age_secs//60)}m ago" if age_secs < 3600 else f"{int(age_secs//3600)}h ago"
            st.caption(f"📦 Data: {saved_dt.strftime('%d %b %I:%M %p')} IST · {age_str}")
        except Exception:
            st.caption("📦 Saved data loaded")
    else:
        st.caption("No cache — use Refresh button above")

    if not symbols:
        st.warning("⚠️ No symbols. Check NSE connection.")

# ══════════════════════════════════════════════════════════════════════════════
# LIVE REFRESH HANDLER
# ══════════════════════════════════════════════════════════════════════════════
refresh_clicked = st.session_state.refresh_requested
if refresh_clicked:
    st.session_state.refresh_requested = False
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
    # ── Header row with refresh button top-right ──
    hcol1, hcol2 = st.columns([5, 1])
    with hcol1:
        st.markdown(f'<p class="page-title">{watchlist_name}</p>'
                    f'<p class="page-sub">{timeframe} timeframe · {len(symbols)} stocks</p>',
                    unsafe_allow_html=True)
    with hcol2:
        if st.button("🔄 Refresh", type="primary", use_container_width=True, key="main_refresh"):
            st.session_state.refresh_requested = True
            st.rerun()
        if st.session_state.saved_at:
            try:
                _ts = datetime.fromisoformat(st.session_state.saved_at).astimezone(IST)
                st.markdown(f'<div class="refresh-ts">{_ts.strftime("%d %b %H:%M")} IST</div>',
                            unsafe_allow_html=True)
            except Exception:
                pass

    if st.session_state.df_screen is None:
        st.info("Click **🔄 Refresh** (top right) to load market data.")
        if len(symbols) > 100:
            st.warning(f"⏱ {watchlist_name} has {len(symbols)} stocks. First load ≈ {len(symbols)//120 + 1}–{len(symbols)//80 + 1} min. Subsequent page loads use saved cache instantly.")
    else:
        df = st.session_state.df_screen.copy()

        # ── Compute stats ──
        g   = int((df["Change%"] > 0).sum()) if "Change%" in df.columns else 0
        lo  = int((df["Change%"] < 0).sum()) if "Change%" in df.columns else 0
        rsi_col = "RSI_D" if "RSI_D" in df.columns else ("RSI" if "RSI" in df.columns else None)
        ob  = int((df[rsi_col] >= 70).sum()) if rsi_col else 0
        os_ = int((df[rsi_col] <= 30).sum()) if rsi_col else 0
        if all(c in df.columns for c in ["above_sma20","above_sma50","above_sma200"]):
            ma_all = int((df["above_sma20"].astype(bool) &
                          df["above_sma50"].astype(bool) &
                          df["above_sma200"].astype(bool)).sum())
        else:
            ma_all = 0
        ath = int(df["Near 52W High"].astype(bool).sum()) if "Near 52W High" in df.columns else 0

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
                if v >= 70: return "background-color:#fee2e2;color:#b91c1c;font-weight:700"
                if v <= 30: return "background-color:#dcfce7;color:#15803d;font-weight:700"
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
            st.caption("Stocks with RSI ≥ 70 on Daily + Weekly + Monthly simultaneously")
            rsi_tf_cols = [rc for rc in ["RSI_D","RSI_W","RSI_M"] if rc in df.columns]
            if not rsi_tf_cols:
                st.markdown('<div class="warn-banner">⚠️ Multi-timeframe RSI not in cached data. Click <b>Refresh</b> to fetch live data.</div>', unsafe_allow_html=True)
            else:
                df_rsi = df.copy()
                for rc in rsi_tf_cols:
                    df_rsi = df_rsi[df_rsi[rc].notna() & (df_rsi[rc] >= 70)]
                st.caption(f"**{len(df_rsi)}** stocks")
                if df_rsi.empty:
                    st.info("No stocks with RSI ≥ 70 across all three timeframes right now.")
                else:
                    st.dataframe(_style_df(df_rsi, currency), use_container_width=True,
                                 hide_index=True, height=400)

        with ft_ma:
            st.caption("Stocks trading above SMA 20, SMA 50, and SMA 200 simultaneously")
            ma_flag_cols = [c for c in ["above_sma20","above_sma50","above_sma200"] if c in df.columns]
            if not ma_flag_cols:
                st.markdown('<div class="warn-banner">⚠️ MA data not in cached data. Click <b>Refresh</b> to fetch live data.</div>', unsafe_allow_html=True)
            else:
                df_ma = df.copy()
                for col_flag in ma_flag_cols:
                    df_ma = df_ma[df_ma[col_flag].astype(bool)]
                st.caption(f"**{len(df_ma)}** stocks above all three MAs")
                if df_ma.empty:
                    st.info("No stocks above all three MAs right now.")
                else:
                    st.dataframe(_style_df(df_ma, currency), use_container_width=True,
                                 hide_index=True, height=400)

        with ft_52w:
            st.caption("Stocks within 3% of their 52-week high")
            if "Near 52W High" not in df.columns:
                st.markdown('<div class="warn-banner">⚠️ 52W High data not in cached data. Click <b>Refresh</b> to fetch live data.</div>', unsafe_allow_html=True)
            else:
                df_52 = df[df["Near 52W High"].astype(bool)]
                st.caption(f"**{len(df_52)}** stocks near 52-week high")
                if df_52.empty:
                    st.info("No stocks within 3% of 52-week high right now.")
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
                title=dict(text=chart_symbol, font=dict(size=16, color="#1e293b")),
                xaxis_rangeslider_visible=False, height=520, template="plotly_white",
                yaxis_title=f"Price ({currency})", margin=dict(l=0,r=0,t=40,b=0))
            st.plotly_chart(fig, use_container_width=True)

            fig_vol = go.Figure(go.Bar(x=df_chart.index, y=df_chart["Volume"],
                                       marker_color="#2563eb", opacity=0.7))
            fig_vol.update_layout(height=160, template="plotly_white",
                                   showlegend=False, margin=dict(l=0,r=0,t=10,b=0))
            st.plotly_chart(fig_vol, use_container_width=True)
        else:
            st.error(f"No data for {chart_symbol}")

# ─────────────────────────────────────────────────────────────────────────────
# TAB 3: WATCHLIST MANAGER
# ─────────────────────────────────────────────────────────────────────────────
with tab3:
    st.markdown('<p class="page-title">⭐ Watchlist Manager</p>', unsafe_allow_html=True)

    # ── Screener.in import ──────────────────────────────────────────────────
    with st.expander("📥 Import Watchlists from Screener.in", expanded=False):
        st.markdown("""
Connect your **[Screener.in](https://www.screener.in)** account to import your
watchlists directly. Credentials are used only for this session and **never stored to disk**.

To avoid entering credentials every time, add them to Streamlit secrets:
```toml
[screener]
username = "your@email.com"
password = "yourpassword"
```
""")
        try:
            _si_u = st.secrets["screener"]["username"]
            _si_p = st.secrets["screener"]["password"]
            st.markdown('<div class="cache-banner">✅ Credentials loaded from Streamlit secrets</div>',
                        unsafe_allow_html=True)
        except Exception:
            _si_u, _si_p = "", ""

        sc1, sc2 = st.columns(2)
        with sc1:
            si_user = st.text_input("Screener.in Email / Username",
                                    value=_si_u, key="si_user")
        with sc2:
            si_pass = st.text_input("Password", type="password",
                                    value=_si_p, key="si_pass")

        if st.button("🔗 Connect & Fetch Watchlists", key="si_connect"):
            if not si_user or not si_pass:
                st.error("Enter username and password.")
            else:
                from data.screener_in import login as si_login, fetch_watchlists as si_fetch_wl
                with st.spinner("Logging in to Screener.in…"):
                    _session = si_login(si_user, si_pass)
                if not _session:
                    st.error("❌ Login failed. Check your credentials.")
                else:
                    with st.spinner("Fetching your watchlists…"):
                        _imported = si_fetch_wl(_session)
                    if _imported:
                        st.session_state["si_imported_wl"] = _imported
                        st.success(f"✅ Found {len(_imported)} watchlist(s)!")
                    else:
                        st.warning("No watchlists found or none contain stocks.")

        if st.session_state.get("si_imported_wl"):
            _imp = st.session_state["si_imported_wl"]
            st.subheader("Select watchlists to import:")
            to_import = []
            for _wl_name, _syms in _imp.items():
                if st.checkbox(f"**{_wl_name}** — {len(_syms)} stocks",
                               key=f"si_chk_{_wl_name}"):
                    to_import.append(_wl_name)
                    with st.expander(f"Preview: {_wl_name}"):
                        st.write(", ".join(_syms[:20]) +
                                 (f" … +{len(_syms)-20} more" if len(_syms) > 20 else ""))

            if to_import and st.button("⬇️ Import Selected Watchlists",
                                       type="primary", key="si_do_import"):
                for _wl_name in to_import:
                    _existing = load_custom_watchlists()
                    if _wl_name not in _existing:
                        create_watchlist(_wl_name)
                    for _sym in _imp[_wl_name]:
                        add_symbol_to_watchlist(_wl_name, _sym)
                get_symbols.clear()
                del st.session_state["si_imported_wl"]
                st.success(f"✅ Imported {len(to_import)} watchlist(s)! "
                           "Select them from the sidebar.")
                st.rerun()

    st.divider()
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

            # Add stock — searchable autocomplete from Nifty 500
            with st.form("add_sym_form"):
                _all_syms = sorted(get_symbols("Nifty 500") + get_symbols("Nifty Next 50"))
                _existing = set(wl_syms)
                _choices  = [s for s in _all_syms if s not in _existing]
                ac1, ac2 = st.columns([3,1])
                with ac1:
                    add_sym = st.selectbox(
                        "Search & add symbol (Nifty 500 + Next 50)",
                        [""] + _choices,
                        format_func=lambda x: x if x else "— type to search —",
                        key="add_sym_select")
                with ac2:
                    st.markdown("<br>", unsafe_allow_html=True)
                    add_submitted = st.form_submit_button("Add ➕")
                if add_submitted and add_sym:
                    add_symbol_to_watchlist(selected_wl, add_sym)
                    get_symbols.clear()
                    st.success(f"Added {add_sym}")
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
    st.markdown(f'<div class="cache-banner">WhatsApp: {wa_status} · Phone: {wa_cfg.get("phone","—")}</div>',
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
    st.subheader("🏷 Sector Data (Screener.in)")
    from data.screener_in import get_cache_stats, get_bulk_screener_info
    si_stats = get_cache_stats()
    st.markdown(
        f'<div class="cache-banner">'
        f'Cached: **{si_stats["total_cached"]}** stocks · '
        f'Stale: {si_stats["stale_count"]} · '
        f'Size: {si_stats["size_kb"]} KB</div>',
        unsafe_allow_html=True)
    st.caption("Sector data is scraped from Screener.in public pages and cached for 30 days. "
               "Run this once after a fresh Screener data refresh.")

    if symbols and st.button("📡 Fetch Sector Data for Current Index",
                              key="fetch_sector", type="primary"):
        pb = st.progress(0, text=f"Fetching sector data for {len(symbols)} stocks…")

        def _prog(done, total):
            pb.progress(done / total,
                        text=f"Fetching sector… {done}/{total}")

        with st.spinner("Scraping screener.in — this runs once and is cached 30 days…"):
            get_bulk_screener_info(symbols, on_progress=_prog)
        pb.empty()
        st.success(f"✅ Sector data fetched for {len(symbols)} stocks! "
                   "Click **Refresh** on the Screener tab to reload with sector info.")

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
