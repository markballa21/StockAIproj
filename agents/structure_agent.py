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
אתה סוכן מבנה שוק (15m / 1H). עליך להחזיר JSON תקין בלבד:
{{
  "in_value_zone": true,
  "suggested_sl": 0.0,
  "suggested_tp": 0.0,
  "risk_reward_ratio": 2.0,
  "reasoning": "נימוק קצר בשורה אחת"
}}

נכס: {symbol} | כיוון מאושר: {bias}
נתוני מבנה:
{json.dumps(struct_data, ensure_ascii=False)}

חוקים:
{custom_rules or 'אשר in_value_zone רק בקרבה לתמיכה/התנגדות עם יחס סיכון/סיכוי טוב.'}
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