# agents/schemas.py
from typing import Literal, Optional
from pydantic import BaseModel, Field


class MacroDecision(BaseModel):
    bias: Literal["BULLISH", "BEARISH", "NEUTRAL"] = Field(
        description="כיוון המגמה הראשית"
    )
    confidence: float = Field(
        ge=0.0, le=1.0, description="רמת ביטחון בניתוח בין 0 ל-1"
    )
    reasoning: str = Field(description="הסבר תמציתי על מבנה המאקרו והרמות")


class StructureDecision(BaseModel):
    in_value_zone: bool = Field(
        description="האם המחיר באזור עניין מתאים לכניסה"
    )
    suggested_sl: float = Field(description="מחיר Stop Loss מבני מומלץ")
    suggested_tp: float = Field(description="מחיר Take Profit מבני מומלץ")
    risk_reward_ratio: float = Field(description="יחס הסיכון לסיכוי המחושב")
    reasoning: str = Field(description="הסבר על אזור הערך והרמות המבניות")


class TriggerDecision(BaseModel):
    trigger_confirmed: bool = Field(
        description="האם התקבל אישור כניסה לפי VWAP, RVOL ונרות"
    )
    entry_price: float = Field(description="מחיר כניסה מוצע לפקודה")
    timing_confidence: float = Field(
        ge=0.0, le=1.0, description="ציון איכות התזמון בין 0 ל-1"
    )
    reasoning: str = Field(description="הסבר קצר על הנפח ואישור הטריגר")


class TradeEvaluationResult(BaseModel):
    action: Literal["BUY", "SELL", "HOLD"]
    symbol: str
    stage_failed: Optional[str] = None
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    risk_reward_ratio: Optional[float] = None
    confidence: float = 0.0
    reasoning: str