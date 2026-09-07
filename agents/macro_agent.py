# agents/macro_agent.py
import json
from typing import Any, Dict
import anthropic
from agents.schemas import MacroDecision

class MacroAgent:
    def __init__(self, client: anthropic.Anthropic, model_name: str = "claude-haiku-4-5-20251001"):
        self.client = client
        self.model_name = model_name

    def analyze(self, symbol: str, macro_data: Dict[str, Any], custom_rules: str = "") -> MacroDecision:
        prompt = f"""
אתה סוכן מאקרו בכיר למסחר במניות. עליך להחזיר תשובה בפורמט JSON בלבד, ללא מלל נוסף.
מבנה ה-JSON הנדרש:
{{"bias": "BULLISH" | "BEARISH" | "NEUTRAL", "confidence": float, "reasoning": "string"}}

נכס: {symbol}
נתונים יומיים: {json.dumps(macro_data)}
חוקים מיוחדים: {custom_rules}
"""
        try:
            response = self.client.messages.create(
                model=self.model_name,
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}]
            )
            raw_text = response.content[0].text.strip()
            if raw_text.startswith("```"):
                raw_text = raw_text.split("```")[1].replace("json", "").strip()
            return MacroDecision.model_validate_json(raw_text)
        except Exception as e:
            return MacroDecision(bias="NEUTRAL", confidence=0.0, reasoning=f"Claude Macro error: {str(e)}")