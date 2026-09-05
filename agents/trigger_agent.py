# agents/trigger_agent.py
from typing import Any, Dict
from google import genai
from google.genai import types

from agents.schemas import TriggerDecision


class TriggerAgent:
    def __init__(self, client: genai.Client, model_name: str = "gemini-2.5-flash"):
        self.client = client
        self.model_name = model_name

    def analyze(self, symbol: str, bias: str, trigger_data: Dict[str, Any], custom_rules: str = "") -> TriggerDecision:
        prompt = f"""
        אתה סוכן תזמון וטריגרים למסחר תוך-יומי מהיר (Trigger & Execution Agent).
        כיוון מאושר: {bias}
        נכס: {symbol}

        נתונים מהירים (1m / 5m):
        - מחיר נוכחי: {trigger_data.get('close')}
        - VWAP: {trigger_data.get('vwap')}
        - נפח יחסי (RVOL): {trigger_data.get('rvol')}
        - EMA 20: {trigger_data.get('ema_20')}
        - EMA 50: {trigger_data.get('ema_50')}

        חוקי כניסה:
        1. ל-BUY: מחיר מעל VWAP, RVOL >= 1.2, ומגמה חיובית (EMA 20 > EMA 50 או Close > EMA 20).
        2. ל-SELL: מחיר מתחת ל-VWAP, RVOL >= 1.2, ומגמה שלילית (EMA 20 < EMA 50 או Close < EMA 20).
        {custom_rules}
        """

        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=TriggerDecision,
                    temperature=0.1
                )
            )
            return TriggerDecision.model_validate_json(response.text)
        except Exception as e:
            return TriggerDecision(
                trigger_confirmed=False,
                entry_price=0.0,
                timing_confidence=0.0,
                reasoning=f"Trigger agent error: {str(e)}"
            )