# test_executor.py
import logging
from src.executor import AlpacaExecutor

logging.basicConfig(level=logging.INFO)

def test_paper_execution():
    print("🧪 בודק תקשורת ושיגור פקודות מול חשבון ה-Paper באלפקא...")
    executor = AlpacaExecutor()

    # 1. בדיקת שליפת נתוני חשבון
    summary = executor.get_account_summary()
    print(f"💰 נתוני חשבון: Equity=${summary['equity']:,.2f} | Buying Power=${summary['buying_power']:,.2f}")
    assert summary["equity"] > 0, "שגיאה במשיכת יתרת חשבון"

    # 2. סימולציית החלטת AI
    mock_decision = {
        "action": "BUY",
        "symbol": "AAPL",
        "entry_price": 200.00,
        "stop_loss": 196.00,
        "take_profit": 208.00,
    }

    # 3. בדיקת חישוב כמות מניות
    shares = executor.calculate_position_size(
        entry_price=mock_decision["entry_price"],
        stop_loss=mock_decision["stop_loss"],
        risk_per_trade_pct=0.01
    )
    print(f"📊 כמות מניות מחושבת לסיכון 1%: {shares} מניות")

    # 4. שיגור פקודת דמו
    order = executor.submit_bracket_order(mock_decision)
    if order:
        print(f"✅ פקודה שוגרה בהצלחה לחשבון ה-Paper! מזהה פקודה: {order.id}")
        # ביטול הפקודה מיד לצורך הבדיקה
        executor.client.cancel_order_by_id(order.id)
        print("🗑️ הפקודה בוטלה בהצלחה.")

if __name__ == "__main__":
    test_paper_execution()