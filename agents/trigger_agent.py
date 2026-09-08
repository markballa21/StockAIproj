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
אתה סוכן טריגר וביצוע (1m / 5m). עליך להחזיר JSON תקין בלבד:
{{
  "trigger_confirmed": true,
  "entry_price": 0.0,
  "timing_confidence": 0.85,
  "reasoning": "נימוק קצר בשורה אחת"
}}

נכס: {symbol} | כיוון: {bias}
נתוני טריגר:
{json.dumps(trigger_data, ensure_ascii=False)}

חוקים:
{custom_rules or 'אשר טריגר רק כאשר יש ווליום פריצה ומחיר בצד הנכון של ה-VWAP.'}
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