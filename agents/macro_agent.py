# agents/macro_agent.py
from typing import Any, Dict
from google import genai
from google.genai import types

from agents.schemas import MacroDecision


class MacroAgent:
    def __init__(self, client: genai.Client, model_name: str = "gemini-2.5-flash"):
        self.client = client
        self.model_name = model_name

    def analyze(self, symbol: str, macro_data: Dict[str, Any], custom_rules: str = "") -> MacroDecision:
        prompt = f"""
        אתה סוכן מאקרו בכיר (Macro Trend Analyst) למסחר במניות.
        תפקידך לנתח את מגמת העל של הנכס על פי נרות יומיים ו-4 שעתיים בלבד.

        נכס: {symbol}
        נתוני מאקרו:
        - מחיר סגירה אחרון: {macro_data.get('close')}
        - מגמה טכנית (SMA 150/EMA): {macro_data.get('trend_regime', 'UNKNOWN')}
        - תמיכה שבועית/יומית: {macro_data.get('nearest_support')}
        - התנגדות שבועית/יומית: {macro_data.get('nearest_resistance')}
        - מרחק מתמיכה (%): {macro_data.get('dist_to_support_pct', 0.0)}%
        - מרחק מהתנגדות (%): {macro_data.get('dist_to_resistance_pct', 0.0)}%

        הנחיות וחוקים נוספים:
        {custom_rules or 'אשר לונג רק אם המחיר מעל הממוצעים ומחזיק תמיכה. אשר שורט רק במגמה יורדת.'}
        """

        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=MacroDecision,
                    temperature=0.1
                )
            )
            return MacroDecision.model_validate_json(response.text)
        except Exception as e:
            return MacroDecision(
                bias="NEUTRAL",
                confidence=0.0,
                reasoning=f"Macro agent error: {str(e)}"
            )