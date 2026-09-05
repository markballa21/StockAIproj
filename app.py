
from config import Config
import streamlit as st

st.set_page_config(
    page_title="AI Trading Terminal",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("🤖 AI Multi-Agent Quantitative Trading Terminal")
st.markdown("---")

config = Config()

col1, col2, col3, col4 = st.columns(4)
col1.metric("Database Path", config.DB_PATH)
col2.metric("Execution Mode", "Paper Trading" if config.IS_PAPER else "Live")
col3.metric("Watchlist Size", f"{len(config.WATCHLIST)} Stocks")
col4.metric("Risk Sizing", "1% Per Trade")

st.markdown("""
### 🧭 בחר אזור פעילות מהתפריט בצד:
1. **📡 Live Trading:** צפייה בלייב בנימוקי ה-AI, בפוזיציות הפתוחות ובסטטוס המסחר.
2. **🔍 SQL Explorer:** בדיקת תקינות הדאטה ב-SQLite, הרצת שאילתות וסקירת נרות גולמיים.
3. **🧪 Backtesting:** הרצת סימולציה היסטורית נר-אחר-נר על מניה בודדת או קבוצת מניות.
""")