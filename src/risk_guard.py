# src/risk_guard.py
from datetime import datetime
import pytz
from typing import List, Tuple


class HardRiskGuard:
    def __init__(self, max_positions: int = 3, max_daily_losses: int = 2):
        self.max_positions = max_positions
        self.max_daily_losses = max_daily_losses
        self.ny_tz = pytz.timezone("America/New_York")
        self.active_symbols: List[str] = []
        self.daily_loss_count: int = 0

    def can_open_trade(self, symbol: str) -> Tuple[bool, str]:
        # 1. מגבלת הפסדים
        if self.daily_loss_count >= self.max_daily_losses:
            return False, f"Circuit Breaker: Hit {self.daily_loss_count} losses today."

        # 2. מגבלת כמות פוזיציות
        if len(self.active_symbols) >= self.max_positions:
            return False, f"Max positions reached ({len(self.active_symbols)}/{self.max_positions})."

        # 3. מניעת כניסה כפולה
        if symbol in self.active_symbols:
            return False, f"Position already active for {symbol}."

        # 4. חלונות זמן (EST)
        now_ny = datetime.now(self.ny_tz)
        current_hm = now_ny.strftime("%H:%M")
        if "09:30" <= current_hm < "09:40":
            return False, "Opening volatility buffer: No trading first 10 minutes."
        if current_hm >= "15:50":
            return False, "EOD cutoff: No entries after 15:50 EST."

        return True, "Risk checks passed."

    def register_new_trade(self, symbol: str) -> None:
        """רישום פתיחת טרייד חדש במעקב הפנימי"""
        if symbol not in self.active_symbols:
            self.active_symbols.append(symbol)

    def register_trade_result(self, symbol: str, is_loss: bool) -> None:
        """עדכון סטטוס בסגירת עסקה"""
        if symbol in self.active_symbols:
            self.active_symbols.remove(symbol)
        if is_loss:
            self.daily_loss_count += 1