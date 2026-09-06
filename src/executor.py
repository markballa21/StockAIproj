# src/executor.py
import logging
from typing import Optional, Dict, Any
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    LimitOrderRequest,
    MarketOrderRequest,
    TakeProfitRequest,
    StopLossRequest,
)
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass
from config import Config

logger = logging.getLogger("AlpacaExecutor")

class AlpacaExecutor:
    def __init__(self, is_paper: Optional[bool] = None):
        self.config = Config()
        paper_mode = is_paper if is_paper is not None else self.config.IS_PAPER
        self.client = TradingClient(
            api_key=self.config.ALPACA_KEY,
            secret_key=self.config.ALPACA_SECRET,
            paper=paper_mode
        )
        logger.info(f"✅ AlpacaExecutor אותחל בהצלחה (Paper={paper_mode})")

    def get_account_summary(self) -> Dict[str, float]:
        account = self.client.get_account()
        return {
            "equity": float(account.equity),
            "buying_power": float(account.buying_power),
            "cash": float(account.cash),
            "daily_pnl": float(account.equity) - float(account.last_equity)
        }

    def calculate_position_size(
        self,
        entry_price: float,
        stop_loss: float,
        risk_per_trade_pct: float = 0.01
    ) -> int:
        acc = self.get_account_summary()
        risk_dollars = acc["equity"] * risk_per_trade_pct
        per_share_risk = abs(entry_price - stop_loss)

        if per_share_risk <= 0.01:
            per_share_risk = entry_price * 0.005

        shares = int(risk_dollars / per_share_risk)
        max_possible_shares = int(acc["buying_power"] / entry_price)
        return max(1, min(shares, max_possible_shares))

    def submit_bracket_order(self, decision: Dict[str, Any], use_limit: bool = True) -> Optional[Any]:
        """שיגור פקודת Bracket מאומתת"""
        symbol = decision.get("symbol")
        action = decision.get("action")
        entry_price = round(float(decision.get("entry_price", 0.0)), 2)
        stop_loss = round(float(decision.get("stop_loss", 0.0)), 2)
        take_profit = round(float(decision.get("take_profit", 0.0)), 2)

        if action not in ["BUY", "SELL"]:
            return None

        # ולידציה לכיוון העסקה מול אלפקא
        if action == "BUY" and not (stop_loss < entry_price < take_profit):
            logger.error(f"🛑 ערכי מחיר לא תקינים ל-BUY: SL ({stop_loss}) < Entry ({entry_price}) < TP ({take_profit})")
            return None
        elif action == "SELL" and not (take_profit < entry_price < stop_loss):
            logger.error(f"🛑 ערכי מחיר לא תקינים ל-SELL: TP ({take_profit}) < Entry ({entry_price}) < SL ({stop_loss})")
            return None

        qty = self.calculate_position_size(entry_price, stop_loss)
        side = OrderSide.BUY if action == "BUY" else OrderSide.SELL

        if use_limit:
            order_data = LimitOrderRequest(
                symbol=symbol,
                qty=qty,
                side=side,
                limit_price=entry_price,
                time_in_force=TimeInForce.GTC,
                order_class=OrderClass.BRACKET,
                take_profit=TakeProfitRequest(limit_price=take_profit),
                stop_loss=StopLossRequest(stop_price=stop_loss)
            )
        else:
            order_data = MarketOrderRequest(
                symbol=symbol,
                qty=qty,
                side=side,
                time_in_force=TimeInForce.GTC,
                order_class=OrderClass.BRACKET,
                take_profit=TakeProfitRequest(limit_price=take_profit),
                stop_loss=StopLossRequest(stop_price=stop_loss)
            )

        try:
            order = self.client.submit_order(order_data=order_data)
            logger.info(f"🚀 פקודת Bracket שוגרה! ID: {order.id} | {action} {qty} {symbol} @ {entry_price} (SL: {stop_loss}, TP: {take_profit})")
            return order
        except Exception as e:
            logger.error(f"❌ שגיאה בשיגור פקודה מול Alpaca עבור {symbol}: {e}")
            return None