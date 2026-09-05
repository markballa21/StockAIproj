# agents/orchestrator.py
from typing import Any, Dict, Optional
from google import genai

from agents.macro_agent import MacroAgent
from agents.structure_agent import StructureAgent
from agents.trigger_agent import TriggerAgent
from agents.schemas import TradeEvaluationResult


class TradingOrchestrator:
    def __init__(self, api_key: str = "", model_name: str = "gemini-2.5-flash"):
        self.client = genai.Client(api_key=api_key) if api_key else genai.Client()
        self.macro_agent = MacroAgent(self.client, model_name)
        self.structure_agent = StructureAgent(self.client, model_name)
        self.trigger_agent = TriggerAgent(self.client, model_name)

    def evaluate_symbol(
        self,
        symbol: str,
        data_bundle: Dict[str, Dict[str, Any]],
        rules_pack: Optional[Dict[str, Any]] = None,
        min_rr_ratio: float = 1.5
    ) -> TradeEvaluationResult:
        rules = rules_pack or {}

        # -------------------------------------------------------------
        # 1. שלב מאקרו (Daily / 4H)
        # -------------------------------------------------------------
        macro_rules = rules.get("macro", {}).get("custom_notes", "")
        macro_res = self.macro_agent.analyze(symbol, data_bundle.get("macro", {}), macro_rules)

        if macro_res.bias == "NEUTRAL":
            return TradeEvaluationResult(
                action="HOLD",
                symbol=symbol,
                stage_failed="MACRO",
                confidence=macro_res.confidence,
                reasoning=f"[Macro Neutral] {macro_res.reasoning}"
            )

        # -------------------------------------------------------------
        # 2. שלב מבנה שוק (15m / 1H)
        # -------------------------------------------------------------
        struct_rules = rules.get("structure", {}).get("custom_notes", "")
        struct_res = self.structure_agent.analyze(
            symbol=symbol,
            bias=macro_res.bias,
            struct_data=data_bundle.get("structure", {}),
            custom_rules=struct_rules
        )

        if not struct_res.in_value_zone:
            return TradeEvaluationResult(
                action="HOLD",
                symbol=symbol,
                stage_failed="STRUCTURE_ZONE",
                reasoning=f"[Structure] Outside value zone: {struct_res.reasoning}"
            )

        if struct_res.risk_reward_ratio < min_rr_ratio:
            return TradeEvaluationResult(
                action="HOLD",
                symbol=symbol,
                stage_failed="STRUCTURE_RR",
                reasoning=f"[Structure] RR ratio {struct_res.risk_reward_ratio:.2f} is below minimum {min_rr_ratio}"
            )

        # -------------------------------------------------------------
        # 3. שלב טריגר (1m / 5m)
        # -------------------------------------------------------------
        trigger_rules = rules.get("trigger", {}).get("custom_notes", "")
        trigger_res = self.trigger_agent.analyze(
            symbol=symbol,
            bias=macro_res.bias,
            trigger_data=data_bundle.get("trigger", {}),
            custom_rules=trigger_rules
        )

        if not trigger_res.trigger_confirmed:
            return TradeEvaluationResult(
                action="HOLD",
                symbol=symbol,
                stage_failed="TRIGGER",
                reasoning=f"[Trigger] Conditions not met: {trigger_res.reasoning}"
            )

        # -------------------------------------------------------------
        # 4. שכבת חישוב וניהול סיכונים סופית (Deterministic Guard)
        # -------------------------------------------------------------
        action = "BUY" if macro_res.bias == "BULLISH" else "SELL"
        entry_price = float(trigger_res.entry_price or data_bundle.get("trigger", {}).get("close", 0.0))

        # שימוש ברמות המבניות אם הן קיימות, או שילוב הגנת ATR
        atr = float(data_bundle.get("trigger", {}).get("atr", 0.50))
        if atr <= 0.05:
            atr = max(0.20, entry_price * 0.002)

        stop_loss = struct_res.suggested_sl
        take_profit = struct_res.suggested_tp

        # בדיקת שפיות מתמטית לכיווני ה-SL וה-TP
        if action == "BUY":
            if stop_loss >= entry_price or stop_loss == 0:
                stop_loss = round(entry_price - (1.5 * atr), 2)
            if take_profit <= entry_price or take_profit == 0:
                take_profit = round(entry_price + (3.0 * atr), 2)
        else:  # SELL
            if stop_loss <= entry_price or stop_loss == 0:
                stop_loss = round(entry_price + (1.5 * atr), 2)
            if take_profit >= entry_price or take_profit == 0:
                take_profit = round(entry_price - (3.0 * atr), 2)

        risk_amount = abs(entry_price - stop_loss)
        reward_amount = abs(take_profit - entry_price)
        final_rr = round(reward_amount / risk_amount, 2) if risk_amount > 0 else 0.0

        confidence = round((macro_res.confidence + trigger_res.timing_confidence) / 2, 2)

        return TradeEvaluationResult(
            action=action,
            symbol=symbol,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            risk_reward_ratio=final_rr,
            confidence=confidence,
            reasoning=f"[Macro] {macro_res.reasoning} | [Structure] {struct_res.reasoning} | [Trigger] {trigger_res.reasoning}"
        )