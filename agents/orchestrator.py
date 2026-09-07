# agents/orchestrator.py
from typing import Any, Dict, Optional
import logging
import anthropic

from agents.macro_agent import MacroAgent
from agents.structure_agent import StructureAgent
from agents.trigger_agent import TriggerAgent
from config import Config
from agents.schemas import MacroDecision, StructureDecision, TriggerDecision

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

    def pre_filter_check(self, trigger_data: Dict[str, Any]) -> tuple[bool, str]:
        """סינון מתמטי מקדים ב-RAM ללא פנייה ל-AI (חוסך מעל 85% מקריאות ה-API)."""
        rvol = trigger_data.get("rvol", 1.0)
        vwap_dist_atr = trigger_data.get("vwap_dist_atr", 0.0)

        # 1. סינון נפח חריג / פעילות מינימלית
        if rvol < 1.1:
            return False, f"Filtered: Low RVOL ({rvol:.2f} < 1.1)"

        # 2. סינון דינמי מבוסס תנודתיות מול VWAP
        # אם המחיר רחוק מ-VWAP יותר מ-1.0 ATR, הוא מתוח מדי לכניסה
        if vwap_dist_atr > 1.2:
            return False, f"Filtered: Extended from VWAP ({vwap_dist_atr:.2f} ATR > 1.2 ATR)"

        return True, "Passed pre-filter"

    def evaluate_symbol(
            self,
            symbol: str,
            data_bundle: Dict[str, Any],
            rules_pack: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """הרצת מפל ההחלטות השלם עם Short-Circuiting מול Anthropic API."""
        rules = rules_pack or {}
        macro_data = data_bundle.get("macro", {})
        struct_data = data_bundle.get("structure", {})
        trig_data = data_bundle.get("trigger", {})

        # --- שלב 0: Pre-Filtering מתמטי (חינמי ומהיר) ---
        passed, reason = self.pre_filter_check(trig_data)
        if not passed:
            return {
                "action": "HOLD",
                "symbol": symbol,
                "stage_failed": "PRE_FILTER",
                "confidence": 0.0,
                "reasoning": reason
            }

        # --- שלב 1: סוכן מאקרו ---
        macro_res: MacroDecision = self.macro_agent.analyze(
            symbol=symbol,
            macro_data=macro_data,
            custom_rules=rules.get("macro", {}).get("custom_notes", "")
        )

        if macro_res.bias == "NEUTRAL":
            return {
                "action": "HOLD",
                "symbol": symbol,
                "stage_failed": "MACRO",
                "confidence": macro_res.confidence,
                "reasoning": f"[Macro HOLD] {macro_res.reasoning}"
            }

        # --- שלב 2: סוכן מבנה והיצע/ביקוש ---
        struct_res: StructureDecision = self.structure_agent.analyze(
            symbol=symbol,
            bias=macro_res.bias,
            struct_data=struct_data,
            custom_rules=rules.get("structure", {}).get("custom_notes", "")
        )

        if not struct_res.in_value_zone:
            return {
                "action": "HOLD",
                "symbol": symbol,
                "stage_failed": "STRUCTURE",
                "confidence": 0.0,
                "reasoning": f"[Structure Rejected] {struct_res.reasoning}"
            }

        # --- שלב 3: סוכן טריגר ו-Price Action ---
        trig_res: TriggerDecision = self.trigger_agent.analyze(
            symbol=symbol,
            bias=macro_res.bias,
            trigger_data=trig_data,
            custom_rules=rules.get("trigger", {}).get("custom_notes", "")
        )

        if not trig_res.trigger_confirmed:
            return {
                "action": "HOLD",
                "symbol": symbol,
                "stage_failed": "TRIGGER",
                "confidence": trig_res.timing_confidence,
                "reasoning": f"[Trigger Wait] {trig_res.reasoning}"
            }

        # חישוב דטרמיניסטי סופי של SL/TP מבוסס ATR תוך-יומי (יחס 1:2)
        close_px = trig_data.get("close", 0.0)
        atr = trig_data.get("atr", 0.5)
        action = "BUY" if macro_res.bias == "BULLISH" else "SELL"

        if action == "BUY":
            stop_loss = round(close_px - (1.5 * atr), 2)
            take_profit = round(close_px + (3.0 * atr), 2)
        else:
            stop_loss = round(close_px + (1.5 * atr), 2)
            take_profit = round(close_px - (3.0 * atr), 2)

        return {
            "action": action,
            "symbol": symbol,
            "entry_price": close_px,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "confidence": round((macro_res.confidence + trig_res.timing_confidence) / 2, 2),
            "reasoning": f"[Macro] {macro_res.reasoning} | [Structure] {struct_res.reasoning} | [Trigger] {trig_res.reasoning}"
        }