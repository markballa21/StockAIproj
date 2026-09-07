# test_orchestrator.py
import json
import logging
from config import Config
from agents.orchestrator import TradingOrchestrator

logging.basicConfig(level=logging.INFO)


def run_standalone_test():
    print("🧪 מתחיל בדיקת אימות מבודדת לתזמורת הסוכנים מול Claude...\n")

    config = Config()
    orchestrator = TradingOrchestrator(
        api_key=config.CLAUDE_API_KEY,
        model_name=config.CLAUDE_MODEL
    )

    # -------------------------------------------------------------
    # תרחיש: בדיקת קריאה בודדת ומפולחת
    # -------------------------------------------------------------
    bullish_data_bundle = {
        "macro": {
            "close": 234.50,
            "trend_regime": "BULLISH_ABOVE_SMA150",
            "nearest_support": 228.00,
            "nearest_resistance": 248.00,
            "dist_to_support_pct": 2.77,
            "dist_to_resistance_pct": 5.75
        },
        "structure": {
            "close": 234.50,
            "nearest_support": 233.80,
            "nearest_resistance": 244.00,  # מרחק שמאפשר TP מעל 240
            "dist_to_support_pct": 0.30,  # צמוד לתמיכה
            "atr": 1.20
        },
        "trigger": {
            "close": 234.50,
            "vwap": 233.90,
            "rvol": 2.45,
            "ema_20": 234.10,
            "ema_50": 233.70,
            "atr": 0.45
        }
    }

    rules_pack = {
        "macro": {"custom_notes": "מגמה עולה ומחיר מעל ממוצעים מאשרים BULLISH."},
        "structure": {
            "custom_notes": "המחיר נמצא בצמוד לתמיכה (0.3% מרחק) - זהו אזור קנייה מצוין (in_value_zone: true). אשר כניסה."},
        "trigger": {"custom_notes": "RVOL גבוה מ-1.5 ומחיר מעל VWAP מאשרים טריגר קנייה (trigger_confirmed: true)."}
    }

    print("🤖 שולח נתונים לבדיקה...")
    decision = orchestrator.evaluate_symbol(
        symbol="AAPL",
        data_bundle=bullish_data_bundle,
        rules_pack=rules_pack
    )

    print("\n📄 תוצאת החלטה שהתקבלה מהתזמורת:")
    print(json.dumps(decision, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    try:
        run_standalone_test()
    except Exception as e:
        print(f"\n❌ שגיאה: {e}")
        import traceback

        traceback.print_exc()