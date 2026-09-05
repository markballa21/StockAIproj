# pages/1_📡_Live_Trading.py
import sqlite3
from datetime import datetime, timezone
import pandas as pd
import streamlit as st
from alpaca.trading.client import TradingClient

from config import Config
from src.data_loader import DataLoader
from src.processor import DataProcessor
from src.ui_helpers import color_action, render_candlestick_chart

st.set_page_config(page_title="Live Trading & AI Feed", page_icon="📡", layout="wide")

config = Config()

# =====================================================================
# State & Database Helpers
# =====================================================================
def get_ai_status(db_path: str) -> bool:
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
            res = conn.execute("SELECT value FROM system_settings WHERE key='ai_evaluation_enabled'").fetchone()
            return res[0] == "true" if res else True
    except Exception:
        return True

def set_ai_status(db_path: str, enabled: bool):
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS system_settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
        """)
        conn.execute("""
            INSERT INTO system_settings (key, value)
            VALUES ('ai_evaluation_enabled', ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """, ("true" if enabled else "false",))

@st.cache_resource
def get_trading_client():
    return TradingClient(
        api_key=config.ALPACA_KEY,
        secret_key=config.ALPACA_SECRET,
        paper=config.IS_PAPER,
    )

@st.cache_resource
def get_data_loader():
    return DataLoader(
        api_key=config.ALPACA_KEY,
        secret_key=config.ALPACA_SECRET,
        db_path=config.DB_PATH,
    )

trading_client = get_trading_client()
loader = get_data_loader()

# =====================================================================
# סרגל צד: בקרות AI ורענון
# =====================================================================
st.sidebar.subheader("🤖 AI Orchestrator Controls")
current_ai_state = get_ai_status(config.DB_PATH)
ai_toggle = st.sidebar.toggle(
    "Enable AI Evaluation (Gemini/Claude)",
    value=current_ai_state,
    help="כאשר כבוי, הסטרים שומר נרות בלבד ללא קריאות ל-AI."
)

if ai_toggle != current_ai_state:
    set_ai_status(config.DB_PATH, ai_toggle)
    st.sidebar.success(f"AI is now {'ENABLED ✅' if ai_toggle else 'DISABLED ⏸️'}")

st.sidebar.markdown("---")
st.sidebar.subheader("🔄 Real-Time Feed Settings")
auto_refresh = st.sidebar.checkbox("Auto-Refresh Feed", value=True)
refresh_interval = st.sidebar.slider("Refresh Interval (Seconds)", min_value=2, max_value=20, value=4)

# =====================================================================
# כותרת ראשית
# =====================================================================
st.title("📡 Live AI Agent Decisions & Execution Feed")
status_badge = "🟢 AI ACTIVE" if ai_toggle else "⏸️ STREAM ONLY (AI PAUSED)"
st.caption(f"Status: **{status_badge}** | Connected: `{config.DB_PATH}` | Feed: Alpaca IEX")

# =====================================================================
# Live Dashboard Fragments (מתעדכן אוטומטית בצורה חלקה)
# =====================================================================
@st.fragment(run_every=refresh_interval if auto_refresh else None)
def render_live_dashboard():
    # 1. שליפת מדדי חשבון
    active_positions_count = 0
    daily_pnl = 0.0
    buying_power = 10000.0
    positions = []

    try:
        account = trading_client.get_account()
        positions = trading_client.get_all_positions()
        active_positions_count = len(positions)
        daily_pnl = float(account.equity) - float(account.last_equity)
        buying_power = float(account.buying_power)
    except Exception:
        pass

    # תצוגת מטריקות
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Active Positions", f"{active_positions_count} / {config.MAX_OPEN_POSITIONS}")
    pnl_color = "normal" if daily_pnl >= 0 else "inverse"
    col2.metric("Daily PnL", f"${daily_pnl:+.2f}", delta=f"{daily_pnl:+.2f}", delta_color=pnl_color)
    col3.metric("Buying Power", f"${buying_power:,.2f}")
    circuit_status = "ACTIVE (OK)" if active_positions_count < config.MAX_OPEN_POSITIONS else "MAX POSITIONS HIT"
    col4.metric("Risk Circuit Breaker", circuit_status)

    st.markdown("---")

    tab_decisions, tab_live_candles, tab_positions = st.tabs([
        "🤖 יומן החלטות AI (Decisions)",
        "📈 גרף וניטור נרות לייב (Live 1m Stream)",
        "💼 פוזיציות פתוחות (Positions)",
    ])

    # ------------------- TAB 1: החלטות AI -------------------
    with tab_decisions:
        st.subheader("🤖 Latest AI Agent Decisions")
        query_decisions = """
            SELECT timestamp, symbol, action, confidence, entry_price, stop_loss, take_profit, reasoning 
            FROM ai_decisions 
            ORDER BY timestamp DESC 
            LIMIT 25
        """
        try:
            with sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True) as conn:
                decisions_df = pd.read_sql(query_decisions, conn)

            if not decisions_df.empty:
                styled_df = decisions_df.style.map(color_action, subset=["action"])
                st.dataframe(styled_df, use_container_width=True, height=450)
            else:
                st.info("No decisions recorded yet. Ensure `live_stream_engine.py` is running.")
        except Exception as e:
            st.info(f"Awaiting database table initialization: {e}")

    # ------------------- TAB 2: ניטור נרות חי -------------------
    with tab_live_candles:
        st.subheader("⚡ Live Minute Bars Monitor")
        sym_col, btn_col = st.columns([2, 2])
        selected_live_sym = sym_col.selectbox("בחר מניה לצפייה:", config.WATCHLIST, index=0, key="live_sym_select")

        if btn_col.button(f"📥 השלם נרות מהפתיחה עבור {selected_live_sym}"):
            added = loader.sync_symbol_data(selected_live_sym, "1m", None, 1)
            st.success(f"סונכרנו {added} נרות מהפתיחה!")

        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        candle_query = """
            SELECT timestamp, open, high, low, close, volume 
            FROM candles 
            WHERE ticker = ? AND timeframe = '1m' AND timestamp >= ?
            ORDER BY timestamp ASC
        """
        try:
            with sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True) as conn:
                live_candles_df = pd.read_sql(candle_query, conn, params=(selected_live_sym, f"{today_str} 00:00:00"))

            if live_candles_df.empty:
                fallback_q = "SELECT timestamp, open, high, low, close, volume FROM candles WHERE ticker = ? AND timeframe = '1m' ORDER BY timestamp DESC LIMIT 60"
                with sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True) as conn:
                    live_candles_df = pd.read_sql(fallback_q, conn, params=(selected_live_sym,))
                live_candles_df = live_candles_df.sort_values("timestamp").reset_index(drop=True)

            if not live_candles_df.empty:
                live_candles_df["timestamp"] = pd.to_datetime(live_candles_df["timestamp"])
                proc = DataProcessor(live_candles_df)
                proc.calculate_indicators({"use_vwap": True, "use_ema": False, "use_pivots": False})
                enriched_df = proc.df

                fig = render_candlestick_chart(enriched_df, indicators_config={"show_vwap": True}, height=480)
                st.plotly_chart(fig, use_container_width=True, config={"scrollZoom": True, "displayModeBar": False})

                with st.expander("📄 טבלת נרות אחרונים"):
                    st.dataframe(enriched_df.tail(10), use_container_width=True)
            else:
                st.warning(f"לא נמצאו נרות עבור {selected_live_sym}.")
        except Exception as e:
            st.error(f"שגיאה בהצגת הגרף: {e}")

    # ------------------- TAB 3: פוזיציות -------------------
    with tab_positions:
        st.subheader("💼 Current Open Positions (Paper)")
        if positions:
            pos_data = [{
                "Symbol": p.symbol,
                "Qty": p.qty,
                "Entry Price": f"${float(p.avg_entry_price):.2f}",
                "Current Price": f"${float(p.current_price):.2f}",
                "Unrealized PnL": f"${float(p.unrealized_pl):+.2f}",
                "Change %": f"{float(p.unrealized_plpc)*100:+.2f}%",
            } for p in positions]
            st.dataframe(pd.DataFrame(pos_data), use_container_width=True)
        else:
            st.info("No open positions currently active.")

# רינדור הפרגמנט
render_live_dashboard()