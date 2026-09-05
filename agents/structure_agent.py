# agents/structure_agent.py
from typing import Any, Dict
from google import genai
from google.genai import types

from agents.schemas import StructureDecision


class StructureAgent:
    def __init__(self, client: genai.Client, model_name: str = "gemini-2.5-flash"):
        self.client = client
        self.model_name = model_name

    def analyze(self, symbol: str, bias: str, struct_data: Dict[str, Any], custom_rules: str = "") -> StructureDecision:
        prompt = f"""
        אתה סוכן מבנה שוק תוך-יומי (Market Structure & Supply/Demand Analyst).
        מגמת המאקרו המאושרת: {bias}
        מניה: {symbol}

        נתוני מבנה תוך-יומי (15m/1H):
        - מחיר נוכחי: ${struct_data.get('close')}
        - תמיכת Pivot קרובה: ${struct_data.get('nearest_support')} ({struct_data.get('dist_to_support_pct', 0.0)}% מתחת למחיר)
        - התנגדות Pivot קרובה: ${struct_data.get('nearest_resistance')} ({struct_data.get('dist_to_resistance_pct', 0.0)}% מעל המחיר)
        - תנודתיות תוך-יומית ATR: ${struct_data.get('atr', 1.0)}

        חוקי עבודה:
        1. ל-BUY: המחיר צריך להיות בסמיכות לתמיכה (Pullback to Support) או לאחר פריצה מבנית ברורה.
        2. ל-SELL: המחיר צריך להיות בסמיכות להתנגדות (Pullback to Resistance) או לאחר שבירה מבנית.
        3. חשב Suggested SL מתחת לתמיכה (עבור BUY) או מעל להתנגדות (עבור SELL).
        4. חשב Suggested TP באזור הנזילות הבא (התנגדות ל-BUY / תמיכה ל-SELL).
        5. חשב את יחס ה-Risk/Reward בצורה מדויקת (Target Gain / Risk Amount).
        {custom_rules}
        """

        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=StructureDecision,
                    temperature=0.1
                )
            )
            return StructureDecision.model_validate_json(response.text)
        except Exception as e:
            return StructureDecision(
                in_value_zone=False,
                suggested_sl=0.0,
                suggested_tp=0.0,
                risk_reward_ratio=0.0,
                reasoning=f"Structure agent error: {str(e)}"
            )