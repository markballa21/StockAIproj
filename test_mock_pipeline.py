# agents/orchestrator.py
from typing import Any, Dict, Optional
import logging
import anthropic

from agents.macro_agent import MacroAgent
from agents.structure_agent import StructureAgent
from agents.trigger_agent import TriggerAgent
from config import Config

logger = logging.getLogger(__name__)


class TradingOrchestrator:
    def __init__(self, api_key: str = "", model_name: str = "claude-haiku-4-5-20251001"):
        cfg = Config()
        key = api_key or cfg.CLAUDE_API_KEY
        # אתחול ה-Client של Anthropic
        self.client = anthropic.Anthropic(api_key=key)
        self.macro_agent = MacroAgent(self.client, model_name)
        self.structure_agent = StructureAgent(self.client, model_name)
        self.trigger_agent = TriggerAgent(self.client, model_name)

    def evaluate_symbol(
        self,
        symbol: str,
        data_bundle: Dict[str, Dict[str, Any]],
        rules_pack: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        מריץ את מפל הסוכנים (Waterfall) מול Claude Haiku,
        ומבצע אכיפת סיכונים ו-SL/TP מבוססי ATR.
        """
        try:
            rules = rules_pack or {}

            # -------------------------------------------------------------
            # 1. שלב מאקרו (Daily / 4H)
            # -------------------------------------------------------------
            macro_rules = rules.get("macro", {}).get("custom_notes", "")
            macro_res = self.macro_agent.analyze(
                symbol=symbol,
                macro_data=data_bundle.get("macro", {}),
                custom_rules=macro_rules
            )

            # תמיכה באובייקט Pydantic (MacroDecision)
            bias = getattr(macro_res, "bias", "NEUTRAL")
            macro_conf = getattr(macro_res, "confidence", 0.0)
            macro_reason = getattr(macro_res, "reasoning", "")

            if bias not in ["BULLISH", "BEARISH"]:
                return {
                    "action": "HOLD",
                    "symbol": symbol,
                    "stage_failed": "MACRO",
                    "confidence": float(macro_conf),
                    "reasoning": macro_reason or "No clear macro trend / Neutral"
                }

            # -------------------------------------------------------------
            # 2. שלב מבנה שוק (15m / 1H)
            # -------------------------------------------------------------
            struct_rules = rules.get("structure", {}).get("custom_notes", "")
            struct_res = self.structure_agent.analyze(
                symbol=symbol,
                bias=bias,
                struct_data=data_bundle.get("structure", {}),
                custom_rules=struct_rules
            )

            in_value_zone = getattr(struct_res, "in_value_zone", False)
            struct_reason = getattr(struct_res, "reasoning", "")

            if not in_value_zone:
                return {
                    "action": "HOLD",
                    "symbol": symbol,
                    "stage_failed": "STRUCTURE",
                    "confidence": 0.0,
                    "reasoning": struct_reason or "Price outside value zone"
                }

            # -------------------------------------------------------------
            # 3. שלב טריגר (1m / 5m)
            # -------------------------------------------------------------
            trigger_rules = rules.get("trigger", {}).get("custom_notes", "")
            trigger_payload = data_bundle.get("trigger", {})

            trigger_res = self.trigger_agent.analyze(
                symbol=symbol,
                bias=bias,
                trigger_data=trigger_payload,
                custom_rules=trigger_rules
            )

            trig_confirmed = getattr(trigger_res, "trigger_confirmed", False)
            trig_entry = getattr(trigger_res, "entry_price", None)
            trig_conf = getattr(trigger_res, "timing_confidence", 0.5)
            trig_reason = getattr(trigger_res, "reasoning", "")

            if not trig_confirmed:
                return {
                    "action": "HOLD",
                    "symbol": symbol,
                    "stage_failed": "TRIGGER",
                    "confidence": 0.0,
                    "reasoning": trig_reason or "Volume/VWAP trigger not met"
                }

            # -------------------------------------------------------------
            # 4. שכבת חישוב ואכיפת סיכונים קשיחה (Deterministic Guard)
            # -------------------------------------------------------------
            action = "BUY" if bias == "BULLISH" else "SELL"
            entry_price = float(trig_entry or trigger_payload.get("close", 0.0))

            atr = float(trigger_payload.get("atr", 0.50))
            if atr <= 0.05:
                atr = max(0.20, entry_price * 0.002)

            if action == "BUY":
                stop_loss = round(entry_price - (1.5 * atr), 2)
                take_profit = round(entry_price + (3.0 * atr), 2)
                if take_profit <= entry_price or stop_loss >= entry_price:
                    return {
                        "action": "HOLD",
                        "symbol": symbol,
                        "stage_failed": "RISK_VALIDATION",
                        "confidence": 0.0,
                        "reasoning": "Invalid math: TP must be above entry and SL below entry for BUY."
                    }
            else:  # SELL
                stop_loss = round(entry_price + (1.5 * atr), 2)
                take_profit = round(entry_price - (3.0 * atr), 2)
                if take_profit >= entry_price or stop_loss <= entry_price:
                    return {
                        "action": "HOLD",
                        "symbol": symbol,
                        "stage_failed": "RISK_VALIDATION",
                        "confidence": 0.0,
                        "reasoning": "Invalid math: TP must be below entry and SL above entry for SELL."
                    }

            confidence = round((float(macro_conf) + float(trig_conf)) / 2, 2)

            return {
                "action": action,
                "symbol": symbol,
                "entry_price": entry_price,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "confidence": confidence,
                "reasoning": f"[Macro] {macro_reason} | [Structure] {struct_reason} | [Trigger] {trig_reason}"
            }

        except Exception as e:
            logger.error(f"Error during orchestrator evaluation for {symbol}: {e}")
            return {
                "action": "HOLD",
                "symbol": symbol,
                "stage_failed": "EXCEPTION",
                "confidence": 0.0,
                "entry_price": 0.0,
                "stop_loss": 0.0,
                "take_profit": 0.0,
                "reasoning": f"Claude Orchestrator error: {str(e)}"
            }