"""
agents/macro_agent.py: סוכן ניתוח מגמת-על (1D / 4H) מול Claude.
"""
import json
import re
from typing import Any, Dict
import anthropic
from agents.schemas import MacroDecision


class MacroAgent:
    def __init__(self, client: anthropic.Anthropic, model_name: str = "claude-haiku-4-5-20251001"):
        self.client = client
        self.model_name = model_name

    def analyze(self, symbol: str, macro_data: Dict[str, Any], custom_rules: str = "") -> MacroDecision:
        prompt = f"""
אתה סוכן מאקרו בכיר למסחר במניות. עליך להחזיר אך ורק אובייקט JSON תקין ללא שום טקסט מקדים או מסכם:
{{
  "bias": "BULLISH" | "BEARISH" | "NEUTRAL",
  "confidence": 0.85,
  "reasoning": "נימוק קצר עד 20 מילים בשורה אחת בלבד"
}}

נכס: {symbol}
נתוני מאקרו (1D):
{json.dumps(macro_data, ensure_ascii=False)}

חוקים:
{custom_rules or 'אשר BULLISH במגמה עולה, BEARISH במגמה יורדת, ו-NEUTRAL בדשדוש.'}
"""
        try:
            response = self.client.messages.create(
                model=self.model_name,
                max_tokens=1500,  # הוגדל מ-300 ל-1500 למניעת קיטום (Truncation)
                messages=[{"role": "user", "content": prompt}]
            )
            raw_text = response.content[0].text.strip()

            # ניקוי Markdown code blocks
            if "```" in raw_text:
                raw_text = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_text, flags=re.MULTILINE).strip()

            # חילוץ האובייקט המסולסל
            json_match = re.search(r"\{.*", raw_text, re.DOTALL)
            if json_match:
                raw_text = json_match.group(0)

            # תיקון מחרוזת חתוכה (אם Claude נעצר באמצע)
            if not raw_text.endswith("}"):
                if not raw_text.endswith('"'):
                    raw_text += '"'
                raw_text += "}"

            return MacroDecision.model_validate_json(raw_text)

        except Exception as e:
            return MacroDecision(
                bias="NEUTRAL",
                confidence=0.0,
                reasoning=f"Claude Macro error: {str(e)[:100]}"
            )