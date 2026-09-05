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
st.title("🧪 Advanced Backtesting & Agent Matrix Hub")

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
# אזור 1: סרגל שליטה ראשי (Universe & Timeline)
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
    help="בחר יום מסחר קיים מ-SQLite",
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
# אזור 2: חלוקת אינדיקטורים ומסגרות זמן לכל סוכן (Agent-Indicator Matrix)
# -------------------------------------------------------------
st.subheader("⚙️ Agent & Indicator Distribution Matrix")
st.caption(
    "בחר בדיוק איזה אינדיקטורים ומסגרות זמן יישלחו לכל סוכן באופן מופרד."
)

col_m, col_s, col_t = st.columns(3)

# 🌐 Macro Agent Configuration
with col_m:
  st.info("🌐 **Macro Agent Config**")
  enable_macro = st.checkbox("Enable Macro Filter", value=True)
  macro_tf = st.selectbox("Macro Timeframe", ["1D", "1H"], index=0)

  macro_sma_choice = st.multiselect("SMAs", [50, 100, 150, 200], default=[150])
  macro_ema_choice = st.multiselect("EMAs", [20, 50, 200], default=[])
  macro_use_sr = st.checkbox("Include Daily Support/Resistance", value=True)

  macro_prompt = st.text_area(
      "Macro Directives",
      "אשר לונג רק מעל קו המגמה הנבחר. פסול דשדוש.",
      height=70,
  )

# 🏗️ Structure Agent Configuration
with col_s:
  st.warning("🏗️ **Structure Agent Config**")
  enable_struct = st.checkbox("Enable Structure Filter", value=True)
  struct_tf = st.selectbox("Structure Timeframe", ["1H", "15m", "5m"], index=1)

  struct_use_pivots = st.checkbox("Pivot High/Low Points", value=True)
  p_left = (
      st.slider("Pivot Left/Right Bars", 2, 10, 5) if struct_use_pivots else 5
  )
  struct_use_atr = st.checkbox("Structure ATR (Volatility)", value=True)
  min_rr = st.slider("Min Risk/Reward (RR)", 1.0, 4.0, 2.0, 0.5)

  struct_prompt = st.text_area(
      "Structure Directives",
      "כניסה אך ורק באזורי ביקוש (Demand). סטופ מתחת לרמה.",
      height=70,
  )

# ⚡ Trigger Agent Configuration
with col_t:
  st.success("⚡ **Trigger Agent Config**")
  enable_trigger = st.checkbox("Enable Trigger Filter", value=True)
  trigger_tf = st.selectbox("Trigger Timeframe", ["5m", "1m"], index=1)

  trig_use_vwap = st.checkbox("Include VWAP", value=True)
  trig_use_rvol = st.checkbox("Include RVOL", value=True)
  rvol_win = st.slider("RVOL Window", 10, 50, 20) if trig_use_rvol else 20
  trig_ema_choice = st.multiselect("Trigger EMAs", [9, 20, 50], default=[20, 50])

  trigger_prompt = st.text_area(
      "Trigger Directives",
      "מחיר מעל VWAP ו-RVOL גבוה מ-1.3. נר פריצה ללא פתיל עליון ארוך.",
      height=70,
  )

# אריזת כל ההגדרות למבנה אחיד
features_config = {
    "macro": {
        "timeframe": macro_tf,
        "sma_spans": macro_sma_choice,
        "ema_spans": macro_ema_choice,
        "use_sr": macro_use_sr,
    },
    "structure": {
        "timeframe": struct_tf,
        "use_pivots": struct_use_pivots,
        "pivot_left_bars": p_left,
        "pivot_right_bars": p_left,
        "use_atr": struct_use_atr,
        "atr_window": 14,
    },
    "trigger": {
        "timeframe": trigger_tf,
        "use_vwap": trig_use_vwap,
        "use_rvol": trig_use_rvol,
        "rvol_window": rvol_win,
        "ema_spans": trig_ema_choice,
    },
}

agents_rules_pack = {
    "macro": {"enabled": enable_macro, "custom_notes": macro_prompt},
    "structure": {
        "enabled": enable_struct,
        "min_rr": min_rr,
        "custom_notes": struct_prompt,
    },
    "trigger": {"enabled": enable_trigger, "custom_notes": trigger_prompt},
}

st.markdown("---")

# -------------------------------------------------------------
# אזור 3: הרצת סימולציה (State Preserved & ThreadPool)
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
    st.info(f"מריץ בקטסטינג על {len(selected_tickers)} מניות...")
    total_trades = []
    daily_pnl = 0.0
    warnings = []

    progress_bar = st.progress(0.0)
    completed_count = 0

    with ThreadPoolExecutor(
        max_workers=min(4, len(selected_tickers))
    ) as executor:
      future_to_ticker = {
          executor.submit(run_single_ticker_sim, t): t for t in selected_tickers
      }
      for future in as_completed(future_to_ticker):
        day_result = future.result()
        if "message" in day_result and not day_result.get("trade_logs"):
          warnings.append(day_result["message"])
        total_trades.extend(day_result.get("trade_logs", []))
        daily_pnl += day_result.get("pnl", 0.0)

        completed_count += 1
        progress_bar.progress(completed_count / len(selected_tickers))

    st.session_state["bt_completed"] = True
    st.session_state["bt_trades"] = total_trades
    st.session_state["bt_pnl"] = daily_pnl
    st.session_state["bt_warnings"] = warnings
    st.rerun()

# -------------------------------------------------------------
# הצגת תוצאות
# -------------------------------------------------------------
if st.session_state.get("bt_completed", False):
  trades = st.session_state.get("bt_trades", [])
  pnl = st.session_state.get("bt_pnl", 0.0)
  for w in st.session_state.get("bt_warnings", []):
    st.warning(w)

  st.success("🏁 תוצאות הסימולציה:")
  m1, m2, m3, m4 = st.columns(4)
  pnl_color = "normal" if pnl >= 0 else "inverse"
  m1.metric("Total PnL ($)", f"${pnl:.2f}", delta=f"{pnl:.2f}", delta_color=pnl_color)
  m2.metric("Total Trades", len(trades))

  win_trades = [t for t in trades if t.get("result") == "WIN"]
  loss_trades = [t for t in trades if t.get("result") == "LOSS"]
  win_rate = (len(win_trades) / len(trades) * 100) if trades else 0.0

  m3.metric("Win Rate (%)", f"{win_rate:.1f}%")
  m4.metric("Wins / Losses", f"{len(win_trades)}W / {len(loss_trades)}L")

  if trades:
    st.subheader("📋 יומן עסקאות ונימוקי ה-AI")
    trades_df = pd.DataFrame(trades)
    display_cols = [
        "ticker",
        "action",
        "entry_time",
        "entry_price",
        "exit_time",
        "exit_price",
        "shares",
        "pnl",
        "result",
        "exit_reason",
        "reasoning",
    ]
    avail = [c for c in display_cols if c in trades_df.columns]
    st.dataframe(trades_df[avail].style.map(color_action, subset=["action"]), use_container_width=True)

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
      st.plotly_chart(fig_pnl, use_container_width=True)