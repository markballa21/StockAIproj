"""
agents/structure_agent.py: סוכן מבנה שוק (15m / 1H) מול Claude.
"""
import json
import re
from typing import Any, Dict
import anthropic
from agents.schemas import StructureDecision


class StructureAgent:
    def __init__(self, client: anthropic.Anthropic, model_name: str = "claude-haiku-4-5-20251001"):
        self.client = client
        self.model_name = model_name

    def analyze(self, symbol: str, bias: str, struct_data: Dict[str, Any], custom_rules: str = "") -> StructureDecision:
        prompt = f"""
        אתה סוכן מבנה שוק והיצע/ביקוש (Market Structure & Value Zone Specialist).
        עליך להחזיר JSON תקין בלבד:
        {{"in_value_zone": bool, "suggested_sl": float, "suggested_tp": float, "risk_reward_ratio": float, "reasoning": "string"}}

        נכס: {symbol} | כיוון מאושר: {bias}
        נתוני מבנה (15m / 1H):
        - מחיר נוכחי: ${struct_data.get('close')}
        - תמיכת Pivot קרובה: ${struct_data.get('nearest_support')} ({struct_data.get('dist_to_support_pct', 0.0)}% מהמחיר)
        - התנגדות Pivot קרובה: ${struct_data.get('nearest_resistance')} ({struct_data.get('dist_to_resistance_pct', 0.0)}% מהמחיר)
        - תנודתיות ATR: ${struct_data.get('atr', 1.0)}

        חוקי איכות (Quality over Quantity):
        1. אשר in_value_zone = True אך ורק כאשר המחיר נמצא בתוך אזור עניין הדוק (עד 0.8% מתמיכה ללונג או מהתנגדות לשורט).
        2. דרוש יחס Risk/Reward מינימלי של לפחות 1:2 ביחס לרמות המבנה.
        3. אם המחיר נמצא באמצע טווח (No Man's Land) – פסול את העסקה מיד (in_value_zone = False).

        חוקים מותאמים:
        {custom_rules or 'אשר כניסה אך ורק באזורי עניין ברורים עם יחס RR >= 2.0.'}
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

            return StructureDecision.model_validate_json(raw_text)

        except Exception as e:
            return StructureDecision(
                in_value_zone=False,
                suggested_sl=0.0,
                suggested_tp=0.0,
                risk_reward_ratio=0.0,
                reasoning=f"Claude Struct error: {str(e)[:100]}"
            )