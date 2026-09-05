"""MarketReplayEngine: מנוע סימולציה ובק-טסטינג נר-אחר-נר ב-RAM.

מדמה יום מסחר מלא (09:30-16:00 EST) מתוך SQLite ללא הצצה לעתיד (Lookahead Bias).
"""

from dataclasses import dataclass
import sqlite3
from typing import Any, Dict, List, Optional
import pandas as pd
import pytz

from agents.orchestrator import TradingOrchestrator
from config import Config
from src.processor import DataProcessor


@dataclass
class ReplayPosition:
  symbol: str
  entry_price: float
  stop_loss: float
  take_profit: float
  entry_time: str
  shares: int
  action: str  # BUY / SELL
  confidence: float
  reasoning: str


class MarketReplayEngine:

  def __init__(self, db_path: str = "market_data.db"):
    self.db_path = db_path
    self.ny_tz = pytz.timezone("America/New_York")
    self.config = Config()
    self.orchestrator = TradingOrchestrator()

  # =========================================================================
  # 1. שליפת נתונים והמרת אזורי זמן (Timezone Alignment)
  # =========================================================================
  def _load_timeframe_history(
      self, ticker: str, timeframe: str, cutoff_iso: str, limit: int
  ) -> pd.DataFrame:
    """שליפת נרות היסטוריים עד לדקה הנוכחית בסימולציה."""
    query = """
            SELECT timestamp, open, high, low, close, volume 
            FROM candles 
            WHERE ticker = ? AND timeframe = ? AND timestamp <= ?
            ORDER BY timestamp DESC 
            LIMIT ?;
        """
    with sqlite3.connect(self.db_path) as conn:
      df = pd.read_sql(query, conn, params=(ticker, timeframe, cutoff_iso, limit))

    if not df.empty:
      df["timestamp"] = pd.to_datetime(df["timestamp"])
      df = df.sort_values("timestamp", ascending=True).reset_index(drop=True)
    return df

  def _load_full_day_1m(self, ticker: str, date_str: str) -> pd.DataFrame:
    """שליפת כל נרות ה-1m של יום הסימולציה מתוך מסד הנתונים."""
    query = """
            SELECT timestamp, open, high, low, close, volume 
            FROM candles 
            WHERE ticker = ? AND timeframe = '1m' AND timestamp LIKE ?
            ORDER BY timestamp ASC;
        """
    with sqlite3.connect(self.db_path) as conn:
      df = pd.read_sql(query, conn, params=(ticker, f"{date_str}%"))

    if df.empty:
      return df

    # המרה ל-Datetime ויישור אזור זמן ל-America/New_York (EST)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    if df["timestamp"].dt.tz is None:
      df["timestamp"] = df["timestamp"].dt.tz_localize("UTC")
    df["timestamp_ny"] = df["timestamp"].dt.tz_convert(self.ny_tz)
    return df

  # =========================================================================
  # 2. מנוע הסימולציה הראשי (Event-Driven Simulation)
  # =========================================================================
  def run_simulation_day(
      self,
      ticker: str,
      date_str: str,
      features_config: Dict[str, Any],
      agents_config: Dict[str, Any],
      capital: float = 10000.0,
      risk_per_trade_pct: float = 0.01,
  ) -> Dict[str, Any]:
    """הרצת יום מסחר מלא עבור מניה תוך דימוי פקודות Bracket ועמלות ריאליות."""
    df_day = self._load_full_day_1m(ticker, date_str)
    if df_day.empty or len(df_day) < 30:
      return {
          "ticker": ticker,
          "date": date_str,
          "pnl": 0.0,
          "trade_logs": [],
          "message": (
              f"אין מספיק נתוני 1 דקה עבור {ticker} בתאריך {date_str} (נמצאו"
              f" {len(df_day)} נרות)."
          ),
      }

    active_position: Optional[ReplayPosition] = None
    trade_logs: List[Dict[str, Any]] = []
    current_balance = float(capital)

    # סימולציה מ-30 נרות ראשונים ועד לסוף היום
    for idx in range(30, len(df_day)):
      current_candle = df_day.iloc[idx]
      ts_ny = current_candle["timestamp_ny"]
      curr_time_str = ts_ny.strftime("%H:%M")
      curr_iso_utc = str(current_candle["timestamp"])

      # -------------------------------------------------------------
      # א. בדיקת פוזיציה פתוחה מול נתוני הנר הנוכחי (SL / TP / EOD)
      # -------------------------------------------------------------
      if active_position is not None:
        exit_event = self._check_position_exit(
            pos=active_position,
            candle=current_candle,
            is_eod=(idx == len(df_day) - 1 or curr_time_str >= "15:58"),
        )
        if exit_event:
          net_pnl = exit_event["pnl"]
          current_balance += net_pnl
          trade_logs.append(exit_event)
          active_position = None
          continue

      # -------------------------------------------------------------
      # ב. חסימת כניסה לפוזיציות חדשות בחצי השעה האחרונה (15:30 EST)
      # -------------------------------------------------------------
      if curr_time_str >= "15:30":
        continue

      # -------------------------------------------------------------
      # ג. הכנת נתוני Multi-Timeframe ב-RAM והפעלת DataProcessor
      # -------------------------------------------------------------
      raw_dfs = {
          "1m": df_day.iloc[: idx + 1][
              ["timestamp", "open", "high", "low", "close", "volume"]
          ].tail(60),
          "15m": self._load_timeframe_history(
              ticker, "15m", curr_iso_utc, limit=50
          ),
          "1D": self._load_timeframe_history(
              ticker, "1D", curr_iso_utc, limit=200
          ),
      }

      # חילוץ ה-Bundle המפולח לכל סוכן
      data_bundle = DataProcessor.build_multi_agent_bundle(
          raw_dfs, features_config
      )

      # -------------------------------------------------------------
      # ד. פנייה לתזמורת הסוכנים לקבלת החלטה
      # -------------------------------------------------------------
      decision = self.orchestrator.evaluate_symbol(
          symbol=ticker, data_bundle=data_bundle, rules_pack=agents_config
      )

      # -------------------------------------------------------------
      # ה. פתיחת פוזיציה במידה והתקבל אישור BUY / SELL
      # -------------------------------------------------------------
      action = decision.get("action")
      if action in ["BUY", "SELL"]:
        entry_price = float(decision.get("entry_price", current_candle["close"]))
        stop_loss = float(decision.get("stop_loss", 0.0))
        take_profit = float(decision.get("take_profit", 0.0))

        # חישוב גודל פוזיציה מבוסס סיכון (1% מגובה החשבון)
        risk_amount = current_balance * risk_per_trade_pct
        per_share_risk = abs(entry_price - stop_loss)
        if per_share_risk <= 0.01:
          per_share_risk = entry_price * 0.005  # 0.5% Fallback

        shares = max(1, int(risk_amount / per_share_risk))
        # הגבלה שלא לחרוג מההון הקיים
        if (shares * entry_price) > current_balance:
          shares = max(1, int(current_balance / entry_price))

        active_position = ReplayPosition(
            symbol=ticker,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            entry_time=str(ts_ny)[:19],
            shares=shares,
            action=action,
            confidence=float(decision.get("confidence", 0.5)),
            reasoning=decision.get("reasoning", ""),
        )

    total_pnl = sum(t["pnl"] for t in trade_logs)
    return {
        "ticker": ticker,
        "date": date_str,
        "pnl": round(total_pnl, 2),
        "trade_logs": trade_logs,
        "ending_balance": round(current_balance, 2),
    }

  # =========================================================================
  # 3. ניהול יציאות, עמלות ריאליות וסגירת עסקאות
  # =========================================================================
  def _check_position_exit(
      self, pos: ReplayPosition, candle: pd.Series, is_eod: bool
  ) -> Optional[Dict[str, Any]]:
    """בדיקת פגיעה ב-SL/TP או סגירת סוף יום וחישוב PnL בניכוי עמלות."""
    high = float(candle["high"])
    low = float(candle["low"])
    close = float(candle["close"])
    ts_str = str(candle["timestamp_ny"])[:19]

    exit_price = None
    exit_reason = None
    result = None

    if pos.action == "BUY":
      if low <= pos.stop_loss:
        exit_price = pos.stop_loss
        exit_reason = "SL_HIT"
        result = "LOSS"
      elif high >= pos.take_profit:
        exit_price = pos.take_profit
        exit_reason = "TP_HIT"
        result = "WIN"
      elif is_eod:
        exit_price = close
        exit_reason = "EOD_CLOSE"
        result = "WIN" if exit_price > pos.entry_price else "LOSS"

    elif pos.action == "SELL":
      if high >= pos.stop_loss:
        exit_price = pos.stop_loss
        exit_reason = "SL_HIT"
        result = "LOSS"
      elif low <= pos.take_profit:
        exit_price = pos.take_profit
        exit_reason = "TP_HIT"
        result = "WIN"
      elif is_eod:
        exit_price = close
        exit_reason = "EOD_CLOSE"
        result = "WIN" if exit_price < pos.entry_price else "LOSS"

    if exit_price is None:
      return None

    # חישוב PnL גולמי
    if pos.action == "BUY":
      gross_pnl = (exit_price - pos.entry_price) * pos.shares
    else:
      gross_pnl = (pos.entry_price - exit_price) * pos.shares

    # מודל עמלות מחמיר: $2.00 קבוע (Round-Trip) + $0.005 לכל מניה
    commission = 2.00 + (pos.shares * 0.005 * 2)
    net_pnl = gross_pnl - commission

    return {
        "ticker": pos.symbol,
        "action": pos.action,
        "entry_time": pos.entry_time,
        "entry_price": round(pos.entry_price, 2),
        "exit_time": ts_str,
        "exit_price": round(exit_price, 2),
        "shares": pos.shares,
        "gross_pnl": round(gross_pnl, 2),
        "commission": round(commission, 2),
        "pnl": round(net_pnl, 2),
        "result": result,
        "exit_reason": exit_reason,
        "reasoning": pos.reasoning,
    }