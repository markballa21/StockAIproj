"""
agents/trigger_agent.py: סוכן טריגר וביצוע (1m / 5m) מול Claude.
"""
import json
import re
from typing import Any, Dict
import anthropic
from agents.schemas import TriggerDecision


class TriggerAgent:
    def __init__(self, client: anthropic.Anthropic, model_name: str = "claude-haiku-4-5-20251001"):
        self.client = client
        self.model_name = model_name

    def analyze(self, symbol: str, bias: str, trigger_data: Dict[str, Any], custom_rules: str = "") -> TriggerDecision:
        prompt = f"""
        אתה סוכן טריגר וביצוע תוך-יומי מהיר (Trigger & Execution Agent).
        עליך להחזיר אך ורק אובייקט JSON תקין ללא שום מלל נוסף, לפי המבנה הבא:
        {{"trigger_confirmed": bool, "entry_price": float, "timing_confidence": float, "reasoning": "string"}}

        כיוון מאקרו ומבנה מאושר: {bias}
        נכס: {symbol}

        נתוני טריגר בנר הנוכחי (1m / 5m):
        - מחיר נוכחי: ${trigger_data.get('close')}
        - קו ה-VWAP: ${trigger_data.get('vwap')}
        - מרחק מ-VWAP בסטיות תקן (Z-Score): {trigger_data.get('vwap_z_score', 0.0)}
        - מרחק מ-VWAP במונחי ATR: {trigger_data.get('dist_to_vwap_atr', 0.0)}
        - נפח יחסי (RVOL): {trigger_data.get('rvol', 1.0)}
        - מדד אגרסיביות נר (-1.0 עד +1.0): {trigger_data.get('bar_aggression', 0.0)}
        - תנודתיות דקתית (ATR): ${trigger_data.get('atr', 0.5)}

        חוקי משמעת וטריגר קשיחים:
        1. חלון כניסות מותר: 09:35 עד 11:00 EST בלבד. לעולם אל תאשר כניסה ב-5 הדקות הראשונות (09:30-09:35) או אחרי 11:00.
        2. חוק עסקה אחת איכותית ליום (Quality over Quantity): אשר כניסה (trigger_confirmed = True) אך ורק אם מדובר בסטאפ בעל סבירות גבוהה מאוד עם פריצת נפח מובהקת (RVOL >= 1.3). אל תאשר כניסות שוליות או נרות דשדוש.
        3. ל-BUY: מחיר מעל VWAP, Z-Score בטווח [0.0, 1.8], ונר פריצה ללא פתיל עליון דומיננטי.
        4. ל-SELL: מחיר מתחת ל-VWAP, Z-Score בטווח [-1.8, 0.0], ונר ירידה החלטי.

        הנחיות מותאמות:
        {custom_rules or 'אשר טריגר רק כאשר מתקיים מומנטום אמיתי, איסוף ווליום מובהק ו-RVOL >= 1.3.'}
        """
        try:
            response = self.client.messages.create(
                model=self.model_name,
                max_tokens=1500,
                messages=[{"role": "user", "content": prompt}]
            )
            raw_text = response.content[0].text.strip()

            if "```" in raw_text:
                raw_text = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_text, flags=re.MULTILINE).strip()

            json_match = re.search(r"\{.*\}", raw_text, re.DOTALL)
            if json_match:
                raw_text = json_match.group(0)

            return TriggerDecision.model_validate_json(raw_text)

        except Exception as e:
            return TriggerDecision(
                trigger_confirmed=False,
                entry_price=0.0,
                timing_confidence=0.0,
                reasoning=f"Claude Trigger error: {str(e)[:100]}"
            )