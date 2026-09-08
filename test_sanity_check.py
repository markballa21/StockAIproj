import os
import sqlite3
import anthropic
from alpaca.trading.client import TradingClient
from config import Config
from src.data_loader import DataLoader
from agents.orchestrator import TradingOrchestrator

def run_preflight_checks():
    print("🔍 מתחיל בדיקות מוכנות למסחר לייב...")
    cfg = Config()

    # 1. בדיקת חיבור לחשבון Alpaca
    try:
        trading_client = TradingClient(api_key=cfg.ALPACA_KEY, secret_key=cfg.ALPACA_SECRET, paper=cfg.IS_PAPER)
        account = trading_client.get_account()
        print(f"✅ חיבור Alpaca תקין | Equity: ${float(account.equity):,.2f} | Paper: {cfg.IS_PAPER}")
    except Exception as e:
        print(f"❌ שגיאת התחברות ל-Alpaca: {e}")
        return

    # 2. בדיקת קריאת API למודל Claude
    try:
        claude_client = anthropic.Anthropic(api_key=cfg.CLAUDE_API_KEY)
        test_msg = claude_client.messages.create(
            model=cfg.CLAUDE_MODEL,
            max_tokens=10,
            messages=[{"role": "user", "content": "ping"}]
        )
        print(f"✅ מפתח Claude תקין ומגיב ({cfg.CLAUDE_MODEL})")
    except Exception as e:
        print(f"❌ שגיאת מפתח Claude / מודל: {e}")
        return

    # 3. בדיקת מסד הנתונים וטבלאות SQLite
    try:
        loader = DataLoader(cfg.ALPACA_KEY, cfg.ALPACA_SECRET, cfg.DB_PATH)
        loader.init_db()
        with sqlite3.connect(cfg.DB_PATH) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
        print(f"✅ מסד נתונים אותחל במצב WAL: {cfg.DB_PATH}")
    except Exception as e:
        print(f"❌ שגיאת מסד נתונים: {e}")
        return

    # 4. בדיקת שרשרת הסוכנים (Mock AI Flow)
    try:
        orchestrator = TradingOrchestrator()
        dummy_bundle = {
            "macro": {"trend_bias": "BULLISH", "sma_150": 230.0, "current_close": 235.0},
            "structure": {"close": 235.0, "nearest_support": 234.0, "nearest_resistance": 242.0, "dist_to_support_pct": 0.4},
            "trigger": {"close": 235.0, "vwap": 234.8, "rvol": 1.4, "atr": 1.1}
        }
        res = orchestrator.evaluate_symbol(symbol="AAPL", data_bundle=dummy_bundle)
        print(f"✅ תזמורת הסוכנים פעילה! החלטה שהתקבלה: {res.get('action')}")
    except Exception as e:
        print(f"❌ שגיאה בהרצת הסוכנים: {e}")
        return

    print("\n🚀 כל הבדיקות עברו בהצלחה! המערכת מוכנה להרצה.")

if __name__ == "__main__":
    run_preflight_checks()