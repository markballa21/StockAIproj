# agents/structure_agent.py
import json
from typing import Any, Dict
import anthropic
from agents.schemas import StructureDecision

class StructureAgent:
    def __init__(self, client: anthropic.Anthropic, model_name: str = "claude-haiku-4-5-20251001"):
        self.client = client
        self.model_name = model_name

    def analyze(self, symbol: str, bias: str, struct_data: Dict[str, Any], custom_rules: str = "") -> StructureDecision:
        prompt = f"""
אתה סוכן מבנה שוק (15m/1H). החזר JSON בלבד:
{{"in_value_zone": bool, "suggested_sl": float, "suggested_tp": float, "risk_reward_ratio": float, "reasoning": "string"}}

נכס: {symbol} | כיוון מאושר: {bias}
נתוני מבנה: {json.dumps(struct_data)}
חוקים: {custom_rules}
"""
        try:
            response = self.client.messages.create(
                model=self.model_name,
                max_tokens=350,
                messages=[{"role": "user", "content": prompt}]
            )
            raw_text = response.content[0].text.strip()
            if raw_text.startswith("```"):
                raw_text = raw_text.split("```")[1].replace("json", "").strip()
            return StructureDecision.model_validate_json(raw_text)
        except Exception as e:
            return StructureDecision(
                in_value_zone=False, suggested_sl=0.0, suggested_tp=0.0,
                risk_reward_ratio=0.0, reasoning=f"Claude Struct error: {str(e)}"
            )