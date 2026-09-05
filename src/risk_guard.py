
from datetime import datetime, timezone
import pytz
from typing import List, Dict, Any


class HardRiskGuard:
    """שכבת בקרת סיכונים קשיחה הנאכפת לפני שיגור כל פקודה."""

    def __init__(self, max_positions: int = 3, max_daily_losses: int = 2):
        self.max_positions = max_positions
        self.max_daily_losses = max_daily_losses
        self.ny_tz = pytz.timezone("America/New_York")

    def can_open_trade(
            self,
            symbol: str,
            current_open_symbols: List[str],
            daily_loss_count: int = 0
    ) -> tuple[bool, str]:
        # 1. בדיקת מגבלת הפסדים יומית
        if daily_loss_count >= self.max_daily_losses:
            return False, f"Circuit Breaker Triggered: Hit {daily_loss_count} losses today."

        # 2. בדיקת כמות פוזיציות פתוחות
        if len(current_open_symbols) >= self.max_positions:
            return False, f"Max Positions Limit Reached ({len(current_open_symbols)}/{self.max_positions})."

        # 3. מניעת כניסה כפולה לאותו נייר
        if symbol in current_open_symbols:
            return False, f"Position already active for {symbol}."

        # 4. חסימת חלונות זמן מסוכנים בניו יורק (09:30-09:40 ו-15:50-16:00)
        now_ny = datetime.now(self.ny_tz)
        current_hm = now_ny.strftime("%H:%M")

        if "09:30" <= current_hm < "09:40":
            return False, "Opening volatility buffer: No trading during first 10 minutes."
        if current_hm >= "15:50":
            return False, "EOD cutoff: No new entries allowed after 15:50 EST."

        return True, "Risk checks passed."