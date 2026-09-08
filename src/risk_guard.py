# src/risk_guard.py
from datetime import datetime
import pytz
from typing import List, Tuple, Set


class HardRiskGuard:
    """שכבת בקרת סיכונים קשיחה ודטרמיניסטית."""

    def __init__(self, max_positions: int = 3, max_daily_losses: int = 2):
        self.max_positions = max_positions
        self.max_daily_losses = max_daily_losses
        self.ny_tz = pytz.timezone("America/New_York")

        # מעקב מצב
        self.active_symbols: Set[str] = set()
        self.symbols_traded_today: Set[str] = set()  # מעקב אחר חוק עסקה אחת ליום
        self.daily_loss_count: int = 0
        self.current_date: str = ""

    def _check_and_reset_day(self, now_ny: datetime) -> None:
        """איפוס יומי אוטומטי של המונים בתחילת יום מסחר חדש."""
        today_str = now_ny.strftime("%Y-%m-%d")
        if self.current_date != today_str:
            self.current_date = today_str
            self.symbols_traded_today.clear()
            self.daily_loss_count = 0

    def can_open_trade(
            self,
            symbol: str,
            current_open_symbols: List[str] = None
    ) -> Tuple[bool, str]:
        now_ny = datetime.now(self.ny_tz)
        self._check_and_reset_day(now_ny)

        # סנכרון פוזיציות פעילות אם הועברה רשימה מבחוץ
        if current_open_symbols is not None:
            self.active_symbols = set(current_open_symbols)

        # 1. בדיקת חלון זמן מסחר מדויק (09:35 - 11:00 EST)
        current_hm = now_ny.strftime("%H:%M")
        if current_hm < "09:35":
            return False, f"Opening buffer: Trading opens only at 09:35 EST (Current: {current_hm})."
        if current_hm >= "11:00":
            return False, f"Session closed: No new entries allowed after 11:00 EST (Mid-day chop filter)."

        # 2. מגבלת הפסדים יומית (Circuit Breaker)
        if self.daily_loss_count >= self.max_daily_losses:
            return False, f"Circuit Breaker Triggered: Hit {self.daily_loss_count} losses today."

        # 3. בדיקת כמות פוזיציות פתוחות במקביל
        if len(self.active_symbols) >= self.max_positions:
            return False, f"Max Positions Limit Reached ({len(self.active_symbols)}/{self.max_positions})."

        # 4. חוק עסקה אחת איכותית למניה ביום (Quality over Quantity)
        if symbol in self.symbols_traded_today or symbol in self.active_symbols:
            return False, f"Single-Trade Rule: {symbol} has already been traded today."

        return True, "Risk checks passed."

    def register_new_trade(self, symbol: str) -> None:
        """רישום פתיחת טרייד – נועל את המניה להמשך היום."""
        self.active_symbols.add(symbol)
        self.symbols_traded_today.add(symbol)

    def register_trade_result(self, symbol: str, is_loss: bool) -> None:
        """עדכון סטטוס בעת סגירת טרייד."""
        self.active_symbols.discard(symbol)
        if is_loss:
            self.daily_loss_count += 1