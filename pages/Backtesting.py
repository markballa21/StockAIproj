# pages/3_🧪_Backtesting.py
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd
import plotly.express as px
import streamlit as st

from config import Config
from src.data_loader import DataLoader
from src.replay_engine import MarketReplayEngine
from src.ui_helpers import color_action

st.set_page_config(page_title="Backtesting & AI Control Lab", layout="wide")
st.title("🧪 Advanced Backtesting & Agent Control Hub")

config = Config()


@st.cache_resource
def get_data_loader():
    return DataLoader(
        api_key=config.ALPACA_KEY,
        secret_key=config.ALPACA_SECRET,
        db_path=config.DB_PATH,
    )


loader = get_data_loader()

# -------------------------------------------------------------
# אזור 1: סרגל שליטה ראשי
# -------------------------------------------------------------
st.sidebar.header("🎯 Universe & Timeline")
summary_db = loader.get_database_summary()
available_tickers = (
    summary_db["ticker"].unique().tolist()
    if not summary_db.empty
    else config.WATCHLIST
)

selected_tickers = st.sidebar.multiselect(
    "Select Stocks",
    options=available_tickers,
    default=[available_tickers[0]] if available_tickers else ["NVDA"],
)

sim_date = st.sidebar.date_input(
    "Simulation Date",
    value=date.today() - timedelta(days=1),
    help="בחר יום מסחר שנשמר ב-SQLite (נרות 1m)",
)

initial_capital = st.sidebar.number_input(
    "Starting Capital ($)", value=10000.0, step=1000.0
)
risk_pct = (
        st.sidebar.slider(
            "Risk Per Trade (%)", min_value=0.5, max_value=3.0, value=1.0, step=0.1
        )
        / 100.0
)

# -------------------------------------------------------------
# אזור 2: שליטה באינדיקטורים
# -------------------------------------------------------------
with st.expander("⚙️ DataProcessor Indicator Configuration", expanded=False):
    st.markdown("בחר אילו חישובים יחושבו ויוזנו כקלט לסוכנים:")
    c1, c2, c3, c4 = st.columns(4)

    use_vwap = c1.checkbox("Include VWAP", value=True)
    use_rvol = c2.checkbox("Include RVOL", value=True)
    rvol_window = c2.slider("RVOL Window", 10, 50, 20) if use_rvol else 20

    use_ema = c3.checkbox("Include EMAs", value=True)
    ema_fast = c3.number_input("Fast EMA", value=20) if use_ema else 20
    ema_slow = c3.number_input("Slow EMA", value=50) if use_ema else 50

    use_atr = c4.checkbox("Include ATR", value=True)
    use_pivots = c4.checkbox("Include Pivot S/R", value=True)

    features_config = {
        "use_vwap": use_vwap,
        "use_rvol": use_rvol,
        "rvol_window": rvol_window,
        "use_ema": use_ema,
        "ema_spans": [int(ema_fast), int(ema_slow)] if use_ema else [],
        "use_atr": use_atr,
        "atr_window": 14,
        "use_pivots": use_pivots,
        "pivot_left_bars": 5,
        "pivot_right_bars": 5,
    }

# -------------------------------------------------------------
# אזור 3: לוח בקרה להנחיות ה-AI
# -------------------------------------------------------------
st.subheader("🤖 AI Agents Multi-Panel Rules & Directives")
col_macro, col_struct, col_trigger = st.columns(3)

with col_macro:
    st.info("🌐 **Macro Agent (1D / 4H)**")
    enable_macro = col_macro.checkbox("Enable Macro Filter", value=True)
    macro_prompt_notes = col_macro.text_area(
        "Rules for Macro",
        "אשר לונג רק מעל SMA 150 ובתמיכה יומית. פסול דשדוש.",
        height=80,
    )

with col_struct:
    st.warning("🏗️ **Structure Agent (1H / 15m)**")
    enable_struct = col_struct.checkbox("Enable Structure Filter", value=True)
    min_rr_ratio = col_struct.slider("Min Risk/Reward", 1.0, 4.0, 2.0, 0.5)
    struct_prompt_notes = col_struct.text_area(
        "Rules for Structure",
        "כניסה אך ורק באזורי Demand או תמיכת Pivot. סטופ מתחת לרמה.",
        height=80,
    )

with col_trigger:
    st.success("⚡ **Trigger Agent (5m / 1m)**")
    enable_trigger = col_trigger.checkbox("Enable Fast Trigger", value=True)
    require_vwap_cross = col_trigger.checkbox("Require VWAP Confirmation", value=True)
    trigger_prompt_notes = col_trigger.text_area(
        "Rules for Trigger",
        "פריצה עם RVOL > 1.3 ומחיר מעל VWAP. ללא פתילים ארוכים.",
        height=80,
    )

agents_rules_pack = {
    "macro": {"enabled": enable_macro, "custom_notes": macro_prompt_notes},
    "structure": {"enabled": enable_struct, "min_rr": min_rr_ratio, "custom_notes": struct_prompt_notes},
    "trigger": {"enabled": enable_trigger, "require_vwap": require_vwap_cross, "custom_notes": trigger_prompt_notes},
}

st.markdown("---")


# -------------------------------------------------------------
# אזור 4: הרצת סימולציה (State-Preserved & ThreadPool)
# -------------------------------------------------------------
def run_single_ticker_sim(ticker: str) -> dict:
    replay = MarketReplayEngine(db_path=config.DB_PATH)
    return replay.run_simulation_day(
        ticker=ticker,
        date_str=str(sim_date),
        features_config=features_config,
        agents_config=agents_rules_pack,
        capital=float(initial_capital),
        risk_per_trade_pct=risk_pct,
    )


if st.button("🚀 Run Backtest Simulation", type="primary"):
    if not selected_tickers:
        st.error("אנא בחר לפחות מניה אחת לסימולציה.")
    else:
        st.info(f"מריץ סימולציה מקבילית על {len(selected_tickers)} מניות עבור תאריך: {sim_date}...")

        total_trades = []
        daily_pnl = 0.0
        warnings = []

        progress_bar = st.progress(0.0)
        completed_count = 0

        # הרצה מקבילית להאצת ביצועים
        with ThreadPoolExecutor(max_workers=min(4, len(selected_tickers))) as executor:
            future_to_ticker = {executor.submit(run_single_ticker_sim, t): t for t in selected_tickers}

            for future in as_completed(future_to_ticker):
                day_result = future.result()
                if "message" in day_result and not day_result.get("trade_logs"):
                    warnings.append(day_result["message"])
                total_trades.extend(day_result.get("trade_logs", []))
                daily_pnl += day_result.get("pnl", 0.0)

                completed_count += 1
                progress_bar.progress(completed_count / len(selected_tickers))

        # שמירה ב-session_state למניעת מחיקה ברענון
        st.session_state["bt_completed"] = True
        st.session_state["bt_trades"] = total_trades
        st.session_state["bt_pnl"] = daily_pnl
        st.session_state["bt_warnings"] = warnings
        st.rerun()

# -------------------------------------------------------------
# הצגת תוצאות מתוך ה-Session State
# -------------------------------------------------------------
if st.session_state.get("bt_completed", False):
    total_trades = st.session_state.get("bt_trades", [])
    daily_pnl = st.session_state.get("bt_pnl", 0.0)
    warnings = st.session_state.get("bt_warnings", [])

    for w in warnings:
        st.warning(w)

    st.success("🏁 תוצאות הסימולציה:")

    # מטריקות
    m1, m2, m3, m4 = st.columns(4)
    pnl_color = "normal" if daily_pnl >= 0 else "inverse"
    m1.metric("Total PnL ($)", f"${daily_pnl:.2f}", delta=f"{daily_pnl:.2f}", delta_color=pnl_color)
    m2.metric("Total Trades", len(total_trades))

    win_trades = [t for t in total_trades if t.get("result") == "WIN"]
    loss_trades = [t for t in total_trades if t.get("result") == "LOSS"]
    win_rate = (len(win_trades) / len(total_trades) * 100) if total_trades else 0.0

    m3.metric("Win Rate (%)", f"{win_rate:.1f}%")
    m4.metric("Wins / Losses", f"{len(win_trades)}W / {len(loss_trades)}L")

    if total_trades:
        st.subheader("📋 Executed Trades & AI Explainability Log")
        trades_df = pd.DataFrame(total_trades)

        display_cols = [
            "ticker", "action", "entry_time", "entry_price",
            "exit_time", "exit_price", "shares", "pnl", "result",
            "exit_reason", "reasoning"
        ]
        available_cols = [c for c in display_cols if c in trades_df.columns]

        styled_trades = trades_df[available_cols].style.map(color_action, subset=["action"])
        st.dataframe(styled_trades, use_container_width=True)

        if len(trades_df) > 1:
            trades_df["cumulative_pnl"] = trades_df["pnl"].cumsum()
            fig_pnl = px.line(
                trades_df,
                x="exit_time",
                y="cumulative_pnl",
                title="Cumulative PnL Over Time ($)",
                markers=True,
                template="plotly_dark",
            )
            st.plotly_chart(fig_pnl, use_container_width=True, config={"scrollZoom": True, "displayModeBar": False})
    else:
        st.warning("לא בוצעו עסקאות ביום זה. סוכני ה-AI סיננו את כל הסטאפים בהתאם לחוקים.")