# pages/2_🔍_SQL_Explorer.py
from datetime import date, timedelta
import pandas as pd
import streamlit as st
from alpaca.data.timeframe import TimeFrame

from config import Config
from src.data_loader import DataLoader
from src.processor import DataProcessor
from src.ui_helpers import render_candlestick_chart

st.set_page_config(page_title="SQL Lab & Chart Explorer", layout="wide")
st.title("🗄️ SQL Terminal & Interactive Candlestick Lab")

config = Config()

@st.cache_resource
def get_data_loader():
    return DataLoader(
        api_key=config.ALPACA_KEY,
        secret_key=config.ALPACA_SECRET,
        db_path=config.DB_PATH,
    )

loader = get_data_loader()

TIMEFRAME_CONFIGS = [
    ("1D", TimeFrame.Day, 365),
    ("1m", TimeFrame.Minute, 30),
]

# פונקציית שליפה עטופה ב-Cache (מונעת פניות חוזרות לדיסק בכל הזזת סליידר)
@st.cache_data(ttl=60)
def fetch_cached_candles(symbol: str, timeframe: str, start_str: str | None, end_str: str | None, limit: int | None):
    return loader.query_candles(
        symbol=symbol,
        timeframe=timeframe,
        start_date=start_str,
        end_date=end_str,
        limit=limit,
        ascending=True,
    )

# =====================================================================
# פאנל סנכרון ואתחול
# =====================================================================
with st.expander("⚡ פאנל מנהל: אתחול מסד נתונים וסנכרון", expanded=False):
    col_input, col_action = st.columns([2, 1])

    with col_input:
        default_tickers_str = ", ".join(config.WATCHLIST)
        custom_tickers = st.text_input(
            "רשימת מניות לסנכרון (מופרדות בפסיק):",
            value=default_tickers_str,
        )

    with col_action:
        st.write("")
        st.write("")
        sync_clicked = st.button("🚀 Run SQL Init / Sync", type="primary", use_container_width=True)

    if sync_clicked:
        tickers_to_sync = [s.strip().upper() for s in custom_tickers.split(",") if s.strip()]
        if not tickers_to_sync:
            st.error("נא להזין לפחות סימבול אחד.")
        else:
            loader.init_db()
            total_added = 0
            progress_bar = st.progress(0.0)
            status_text = st.empty()

            total_steps = len(tickers_to_sync) * len(TIMEFRAME_CONFIGS)
            step = 0

            for symbol in tickers_to_sync:
                for tf_str, tf_alpaca, days in TIMEFRAME_CONFIGS:
                    status_text.text(f"מושך מאלפקא נתוני {symbol} ({tf_str})...")
                    try:
                        rows = loader.sync_symbol_data(symbol, tf_str, tf_alpaca, days)
                        total_added += rows
                    except Exception as e:
                        st.error(f"שגיאה בסנכרון {symbol} ({tf_str}): {e}")
                    step += 1
                    progress_bar.progress(step / total_steps)

                status_text.text(f"מייצר נרות 5m, 15m, 1H מקומית עבור {symbol}...")
                loader.generate_resampled_timeframes(symbol)

            status_text.empty()
            st.cache_data.clear()  # איפוס cache בעת הוספת נתונים חדשים
            st.success(f"✅ הושלם בהצלחה! סונכרנו ועובדו {len(tickers_to_sync)} מניות.")

st.markdown("---")

# =====================================================================
# טאבים לתחקור ויזואלי ושאילתות
# =====================================================================
tab_chart, tab_gaps, tab_overview, tab_sql = st.tabs([
    "📈 גרף נרות אינטראקטיבי (Plotly)",
    "⚠️ זיהוי פערי דאטה (Gap Inspector)",
    "📊 תמונת מצב מסד נתונים",
    "💻 מסוף שאילתות חופשי",
])

# ------------------- TAB 1: גרף נרות -------------------
with tab_chart:
    summary_db = loader.get_database_summary()
    available_symbols = summary_db["ticker"].unique().tolist() if not summary_db.empty else config.WATCHLIST

    col_f1, col_f2, col_f3, col_f4 = st.columns(4)
    selected_sym = col_f1.selectbox("מניה", available_symbols, index=0)
    selected_tf = col_f2.selectbox("מסגרת זמן", ["1m", "5m", "15m", "1H", "1D"], index=0)
    use_date_range = col_f3.checkbox("סנן לפי טווח תאריכים", value=False)

    if use_date_range:
        today = date.today()
        start_d = col_f3.date_input("מתאריך", value=today - timedelta(days=7))
        end_d = col_f4.date_input("עד תאריך", value=today)
        start_str = f"{start_d} 00:00:00"
        end_str = f"{end_d} 23:59:59"
        limit_val = None
    else:
        start_str, end_str = None, None
        limit_val = col_f4.number_input("כמות נרות אחרונים", min_value=20, max_value=2000, value=250)

    # בקרת אינדיקטורים
    with st.expander("🛠️ הגדרות אינדיקטורים ורמות מחיר", expanded=False):
        r1, r2, r3, r4 = st.columns(4)
        show_pivots = r1.checkbox("Pivot Points", value=True)
        show_zones = r2.checkbox("קווי S/R", value=True)
        show_sma = r3.checkbox("הצג SMA", value=True)
        show_ema = r4.checkbox("הצג EMA", value=True)

        r5, r6, r7, r8 = st.columns(4)
        show_vwap = r5.checkbox("הצג VWAP", value=True)
        pivot_left = r6.slider("Left Bars", min_value=2, max_value=20, value=8)
        pivot_right = r7.slider("Right Bars", min_value=2, max_value=20, value=8)
        sma_val = r8.number_input("תקופת SMA", min_value=10, max_value=300, value=150, step=10)

    df_chart = fetch_cached_candles(selected_sym, selected_tf, start_str, end_str, limit_val)

    if df_chart.empty:
        st.warning(f"אין נתונים ב-SQL עבור {selected_sym} במסגרת זמן {selected_tf}.")
    else:
        proc_config = {
            "use_ema": show_ema,
            "ema_spans": [20, 50],
            "use_sma": show_sma,
            "sma_spans": [int(sma_val)],
            "use_vwap": show_vwap,
            "use_rvol": True,
            "use_atr": True,
            "use_pivots": show_pivots or show_zones,
            "pivot_left_bars": pivot_left,
            "pivot_right_bars": pivot_right,
            "use_zones": show_zones
        }

        # --- אחרי התיקון ---
        processor = DataProcessor(df_chart)
        processor.calculate_indicators(proc_config)
        enriched_df = processor.df  # שולף ישירות את ה-DataFrame המעובד עבור Plotly

        fig = render_candlestick_chart(
            enriched_df,
            indicators_config={
                "show_vwap": show_vwap,
                "show_sma": show_sma,
                "sma_val": int(sma_val),
                "show_ema": show_ema,
                "show_pivots": show_pivots,
                "show_zones": show_zones,
            },
            height=600
        )
        st.plotly_chart(fig, use_container_width=True, config={"scrollZoom": True, "displayModeBar": False})

        col_m1, col_m2 = st.columns([2, 1])
        with col_m1:
            st.caption("נתונים אחרונים ב-RAM:")
            st.dataframe(enriched_df.tail(5), use_container_width=True)
        with col_m2:
            st.caption("JSON Payload לסוכני ה-AI:")
            st.json(processor.get_latest_summary())

# ------------------- TAB 2: זיהוי פערים -------------------
with tab_gaps:
    st.subheader(f"🔍 בדיקת פערים ברצף הנרות עבור {selected_sym}")
    gaps = loader.check_data_gaps(selected_sym, selected_tf)
    if not gaps:
        st.success(f"לא זוהו פערי זמן חריגים בנתוני ה-{selected_tf} של {selected_sym}!")
    else:
        st.warning(f"זוהו {len(gaps)} פערי זמן חריגים ברצף המסחר:")
        st.dataframe(pd.DataFrame(gaps), use_container_width=True)

# ------------------- TAB 3: תמונת מצב -------------------
with tab_overview:
    st.subheader("📊 סיכום כללי של מסד הנתונים")
    sum_df = loader.get_database_summary()
    if sum_df.empty:
        st.info("מסד הנתונים ריק. הרץ סנכרון ראשוני למעלה.")
    else:
        st.dataframe(sum_df, use_container_width=True)
        if st.button("🧹 הרץ דחיסת מסד נתונים (SQLite VACUUM)"):
            loader.vacuum_db()
            st.success("בוצעה אופטימיזציה ודחיסת קובץ ה-DB בדיסק.")

# ------------------- TAB 4: מסוף SQL (מוגן Read-Only) -------------------
with tab_sql:
    st.subheader("💻 שאילתת SQL חופשית (Read-Only Mode)")
    raw_query = st.text_area(
        "הזן שאילתה:",
        value="SELECT ticker, timeframe, timestamp, close, volume FROM candles ORDER BY timestamp DESC LIMIT 20;",
        height=100,
    )
    if st.button("הרץ שאילתה ⚡"):
        # חיבור מוגן Read-Only למניעת נעילות
        res_df, err = loader.execute_raw_query(raw_query)
        if err:
            st.error(f"שגיאת SQL: {err}")
        else:
            st.dataframe(res_df, use_container_width=True)