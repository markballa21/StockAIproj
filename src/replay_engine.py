# src/replay_engine.py
import sqlite3
from typing import Any, Dict, List
import pandas as pd
import pytz

from agents.orchestrator import TradingOrchestrator
from config import Config
from src.processor import DataProcessor


class MarketReplayEngine:
    """מנוע סימולציה היסטורי עם תמיכה באזורי זמן, עמלות מחמירות וחוקי זמן קשיחים."""

    def __init__(self, db_path: str = "market_data.db"):
        self.db_path = db_path
        self.config = Config()
        self.orchestrator = TradingOrchestrator(
            api_key=self.config.GEMINI_API_KEY,
            model_name=self.config.GEMINI_MODEL,
        )
        self.ny_tz = pytz.timezone("America/New_York")

    def _fetch_candles_range(
            self, ticker: str, timeframe: str, start_dt: str, end_dt: str
    ) -> pd.DataFrame:
        """שליפת נרות מחלון זמן מוגדר מתוך ה-SQL."""
        query = """
            SELECT timestamp, open, high, low, close, volume 
            FROM candles 
            WHERE ticker = ? AND timeframe = ? AND timestamp BETWEEN ? AND ?
            ORDER BY timestamp ASC
        """
        with sqlite3.connect(self.db_path) as conn:
            df = pd.read_sql_query(
                query, conn, params=(ticker, timeframe, start_dt, end_dt)
            )
        if not df.empty and "timestamp" in df.columns:
            # המרה ל-UTC ומעבר לזמן ניו יורק (EST/EDT)
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
            df["timestamp_est"] = df["timestamp"].dt.tz_convert(self.ny_tz)
        return df

    def calculate_commission(self, shares: int) -> float:
        """חישוב עמלה מחמירה: $2.00 קבוע הלוך ושוב + $0.01 למניה (הלוך-חזור)."""
        flat_fee_roundtrip = 2.00  # $1 קנייה + $1 מכירה
        per_share_fee_roundtrip = shares * 0.01  # $0.005 למניה בכל צד
        return round(flat_fee_roundtrip + per_share_fee_roundtrip, 2)

    def run_simulation_day(
            self,
            ticker: str,
            date_str: str,
            features_config: Dict[str, Any] = None,
            agents_config: Dict[str, Any] = None,
            capital: float = 10000.0,
            risk_per_trade_pct: float = 0.01,
            cutoff_time_str: str = "15:30",  # חסימת עסקאות אחרי 15:30
    ) -> Dict[str, Any]:
        """הרצת יום מסחר מלא עם המרת זמן וחישוב עמלות."""
        # 1. שליפת נתוני מאקרו עד תחילת היום (לפי UTC רחב)
        df_daily = self._fetch_candles_range(
            ticker=ticker,
            timeframe="1D",
            start_dt="2020-01-01 00:00:00",
            end_dt=f"{date_str} 23:59:59",
        )

        macro_payload = {}
        if not df_daily.empty:
            proc_daily = DataProcessor(df_daily)
            proc_daily.calculate_indicators()
            macro_payload = proc_daily.get_latest_summary()

        # 2. שליפת נרות 1 דקה לאותו יום
        df_intraday_raw = self._fetch_candles_range(
            ticker, "1m", f"{date_str} 00:00:00", f"{date_str} 23:59:59"
        )

        if df_intraday_raw.empty:
            return {
                "pnl": 0.0,
                "net_pnl": 0.0,
                "total_commissions": 0.0,
                "trade_logs": [],
                "message": f"No intraday data found for {ticker} on {date_str}",
            }

        # סינון שעות מסחר סדירות בניו יורק (09:30 עד 16:00 EST)
        df_intraday = df_intraday_raw[
            (df_intraday_raw["timestamp_est"].dt.strftime("%H:%M") >= "09:30")
            & (df_intraday_raw["timestamp_est"].dt.strftime("%H:%M") <= "16:00")
            ].copy().reset_index(drop=True)

        if len(df_intraday) < 30:
            return {
                "pnl": 0.0,
                "net_pnl": 0.0,
                "total_commissions": 0.0,
                "trade_logs": [],
                "message": f"Insufficient regular market hours data for {ticker} on {date_str}",
            }

        trade_logs: List[Dict[str, Any]] = []
        current_position: Dict[str, Any] = None
        daily_gross_pnl = 0.0
        daily_commissions = 0.0

        for i in range(25, len(df_intraday)):
            window_slice = df_intraday.iloc[: i + 1].copy()
            current_bar = window_slice.iloc[-1]
            current_price = float(current_bar["close"])
            current_est_str = current_bar["timestamp_est"].strftime("%H:%M:%S")
            current_est_hm = current_bar["timestamp_est"].strftime("%H:%M")

            # א. ניהול סגירת פוזיציה קיימת
            if current_position:
                high_p = float(current_bar["high"])
                low_p = float(current_bar["low"])
                pos_type = current_position["action"]

                hit_tp = False
                hit_sl = False

                if pos_type == "BUY":
                    if high_p >= current_position["tp"]:
                        hit_tp = True
                    elif low_p <= current_position["sl"]:
                        hit_sl = True
                elif pos_type == "SELL":
                    if low_p <= current_position["tp"]:
                        hit_tp = True
                    elif high_p >= current_position["sl"]:
                        hit_sl = True

                is_eod = (i == len(df_intraday) - 1) or (current_est_hm >= "15:59")

                if hit_tp or hit_sl or is_eod:
                    exit_price = (
                        current_position["tp"]
                        if hit_tp
                        else (current_position["sl"] if hit_sl else current_price)
                    )
                    shares = current_position["shares"]
                    trade_gross = (
                        (exit_price - current_position["entry_price"]) * shares
                        if pos_type == "BUY"
                        else (current_position["entry_price"] - exit_price) * shares
                    )

                    commission = self.calculate_commission(shares)
                    trade_net = trade_gross - commission

                    daily_gross_pnl += trade_gross
                    daily_commissions += commission

                    current_position.update(
                        {
                            "exit_time_est": current_est_str,
                            "exit_price": exit_price,
                            "gross_pnl": round(trade_gross, 2),
                            "commission": commission,
                            "net_pnl": round(trade_net, 2),
                            "result": "WIN" if trade_net > 0 else ("LOSS" if trade_net < 0 else "BE"),
                            "exit_reason": "TP_HIT" if hit_tp else ("SL_HIT" if hit_sl else "EOD_CLOSE"),
                        }
                    )
                    trade_logs.append(current_position)
                    current_position = None
                    continue

            # ב. חסימת כניסות חדשות בחצי השעה האחרונה (>= 15:30 EST)
            if current_est_hm >= cutoff_time_str:
                continue

            # ג. עיבוד אינדיקטורים ב-RAM
            processor = DataProcessor(window_slice)
            processor.calculate_indicators(features_config)
            trigger_summary = processor.get_latest_summary()
            structure_summary = trigger_summary.copy()

            bundle = {
                "macro": macro_payload,
                "structure": structure_summary,
                "trigger": trigger_summary,
            }

            # ד. בחינת סטאפ מול סוכני ה-AI
            if not current_position:
                decision = self.orchestrator.evaluate_symbol(
                    symbol=ticker,
                    data_bundle=bundle,
                    rules_pack=agents_config,
                )

                if decision.get("action") in ["BUY", "SELL"]:
                    entry_px = decision.get("entry_price", current_price)
                    sl_px = decision.get(
                        "stop_loss",
                        entry_px * 0.99 if decision["action"] == "BUY" else entry_px * 1.01,
                    )
                    tp_px = decision.get(
                        "take_profit",
                        entry_px * 1.02 if decision["action"] == "BUY" else entry_px * 0.98,
                    )

                    # ניהול סיכונים
                    risk_amount = capital * risk_per_trade_pct
                    risk_per_share = abs(entry_px - sl_px)
                    shares = int(risk_amount / risk_per_share) if risk_per_share > 0 else 10

                    current_position = {
                        "ticker": ticker,
                        "action": decision["action"],
                        "entry_time_est": current_est_str,
                        "entry_price": entry_px,
                        "sl": sl_px,
                        "tp": tp_px,
                        "shares": max(1, shares),
                        "confidence": decision.get("confidence", 0.0),
                        "reasoning": decision.get("reasoning", ""),
                    }

        return {
            "ticker": ticker,
            "date": date_str,
            "gross_pnl": round(daily_gross_pnl, 2),
            "total_commissions": round(daily_commissions, 2),
            "net_pnl": round(daily_gross_pnl - daily_commissions, 2),
            "total_trades": len(trade_logs),
            "trade_logs": trade_logs,
        }