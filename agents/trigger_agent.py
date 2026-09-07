# agents/trigger_agent.py
import json
from typing import Any, Dict
import anthropic
from agents.schemas import TriggerDecision

class TriggerAgent:
    def __init__(self, client: anthropic.Anthropic, model_name: str = "claude-haiku-4-5-20251001"):
        self.client = client
        self.model_name = model_name

    def analyze(self, symbol: str, bias: str, trigger_data: Dict[str, Any], custom_rules: str = "") -> TriggerDecision:
        prompt = f"""
אתה סוכן טריגר וביצוע (1m/5m). החזר JSON בלבד:
{{"trigger_confirmed": bool, "entry_price": float, "timing_confidence": float, "reasoning": "string"}}

נכס: {symbol} | כיוון: {bias}
נתוני טריגר: {json.dumps(trigger_data)}
חוקים: {custom_rules}
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
            return TriggerDecision.model_validate_json(raw_text)
        except Exception as e:
            return TriggerDecision(
                trigger_confirmed=False, entry_price=0.0,
                timing_confidence=0.0, reasoning=f"Claude Trigger error: {str(e)}"
            )