"""
src/live_stream_engine.py: מנוע קליטת WebSocket בזמן אמת (Alpaca IEX),
סינון טכני מקדים ב-RAM, ניהול מפל סוכנים אסינכרוני, שמירת היסטוריה
ושיגור פקודות Paper Trading.
"""
import asyncio
from collections import deque
from datetime import datetime, timezone
import logging
import os
import sqlite3
import sys
from typing import Dict, List, Optional, Tuple

# הבטחת נתיב הפרויקט הראשי ב-sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from alpaca.data.enums import DataFeed
from alpaca.data.live.stock import StockDataStream
import pandas as pd

from agents.orchestrator import TradingOrchestrator
from config import Config
from src.data_loader import DataLoader
from src.executor import AlpacaExecutor
from src.processor import DataProcessor
from src.risk_guard import HardRiskGuard

logger = logging.getLogger("LiveEngine")


class LiveIEXTraderEngine:
    """מנוע מסחר Live ב-WebSocket עם חלון RAM מתגלגל וצינור החלטות היברידי."""

    def __init__(
        self,
        config: Optional[Config] = None,
        orchestrator: Optional[TradingOrchestrator] = None,
        symbols: Optional[List[str]] = None,
    ):
        self.config = config or Config()
        self.symbols = symbols or self.config.WATCHLIST[:3]

        self.loader = DataLoader(
            api_key=self.config.ALPACA_KEY,
            secret_key=self.config.ALPACA_SECRET,
            db_path=self.config.DB_PATH,
        )
        self.orchestrator = orchestrator or TradingOrchestrator()
        self.risk_guard = HardRiskGuard(
            max_positions=getattr(self.config, "MAX_OPEN_POSITIONS", 3),
            max_daily_losses=getattr(self.config, "MAX_DAILY_LOSSES", 2),
        )
        self.executor = AlpacaExecutor()

        self.stream = StockDataStream(
            api_key=self.config.ALPACA_KEY,
            secret_key=self.config.ALPACA_SECRET,
            feed=DataFeed.IEX,
            raw_data=False,
        )

        # ניהול RAM מהיר: 60 נרות אחרונים לכל סימבול
        self.memory_buffers: Dict[str, deque] = {
            s: deque(maxlen=60) for s in self.symbols
        }

        self._init_sqlite_wal()
        self._seed_ram_from_db()

    # -------------------------------------------------------------------------
    # אתחול מסד נתונים וטעינת היסטוריה ל-RAM
    # -------------------------------------------------------------------------
    def _init_sqlite_wal(self) -> None:
        """הגדרת מצב Write-Ahead Logging ומיגרציית סכמה אוטומטית."""
        with sqlite3.connect(self.config.DB_PATH, timeout=30.0) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")

            # יצירת טבלת הנרות אם אינה קיימת
            conn.execute("""
                CREATE TABLE IF NOT EXISTS candles (
                    ticker TEXT,
                    timeframe TEXT,
                    timestamp DATETIME,
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL,
                    volume INTEGER,
                    PRIMARY KEY (ticker, timeframe, timestamp)
                );
            """)

            # יצירת טבלת הגדרות המערכת
            conn.execute("""
                CREATE TABLE IF NOT EXISTS system_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );
            """)

            # יצירת טבלת החלטות ה-AI
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ai_decisions (
                    timestamp DATETIME,
                    symbol TEXT,
                    action TEXT,
                    confidence REAL,
                    entry_price REAL,
                    stop_loss REAL,
                    take_profit REAL,
                    reasoning TEXT,
                    status TEXT DEFAULT 'SUCCESS',
                    error_msg TEXT
                );
            """)

            # וידוא קיום עמודות status ו-error_msg
            cursor = conn.execute("PRAGMA table_info(ai_decisions);")
            cols = [row[1] for row in cursor.fetchall()]
            if "status" not in cols:
                conn.execute("ALTER TABLE ai_decisions ADD COLUMN status TEXT DEFAULT 'SUCCESS';")
            if "error_msg" not in cols:
                conn.execute("ALTER TABLE ai_decisions ADD COLUMN error_msg TEXT;")

    def _seed_ram_from_db(self) -> None:
        """טעינת 60 הנרות האחרונים מה-SQL ל-RAM מיד בעת עליית המנוע."""
        logger.info("🌱 Seeding RAM buffers from SQLite historical candles...")
        for sym in self.symbols:
            try:
                df_init = self.loader.query_candles(
                    symbol=sym, timeframe="1m", limit=60, ascending=True
                )
                if not df_init.empty:
                    for _, row in df_init.iterrows():
                        self.memory_buffers[sym].append({
                            "ticker": sym,
                            "timeframe": "1m",
                            "timestamp": str(row["timestamp"]),
                            "open": float(row["open"]),
                            "high": float(row["high"]),
                            "low": float(row["low"]),
                            "close": float(row["close"]),
                            "volume": float(row["volume"]),
                        })
                    logger.info(f"   ↳ [{sym}] Pre-loaded {len(self.memory_buffers[sym])} candles into RAM.")
            except Exception as e:
                logger.warning(f"Failed to seed RAM for {sym}: {e}")

    def _is_ai_enabled(self) -> bool:
        """בדיקה האם המשתמש הפעיל את ה-AI בלוח הניהול ב-Streamlit."""
        try:
            with sqlite3.connect(self.config.DB_PATH, timeout=5.0) as conn:
                res = conn.execute(
                    "SELECT value FROM system_settings WHERE key='ai_evaluation_enabled'"
                ).fetchone()
                return res[0].lower() == "true" if res else True
        except Exception:
            return True

    # -------------------------------------------------------------------------
    # סינון מתמטי מקדים ב-RAM (Pre-Filter ללא קריאות LLM)
    # -------------------------------------------------------------------------
    @staticmethod
    def passes_pre_filter(
        summary: dict,
        max_atr_dist: float = 1.2,
        max_z_score: float = 2.0,
        min_rvol: float = 1.1,
    ) -> Tuple[bool, str]:
        """סינון מהיר ב-0.1ms למניעת שריפת טוקנים וקריאות API מיותרות."""
        rvol = summary.get("rvol", 1.0)
        if rvol < min_rvol:
            return False, f"Low RVOL ({rvol:.2f} < {min_rvol})"

        dist_atr = summary.get("dist_to_vwap_atr", 0.0)
        if dist_atr > max_atr_dist:
            return False, f"Extended from VWAP ({dist_atr:.2f} ATR > {max_atr_dist} ATR)"

        z_score = abs(summary.get("vwap_z_score", 0.0))
        if z_score > max_z_score:
            return False, f"Extended in StdDev (Z-Score {z_score:.2f} > {max_z_score})"

        return True, "Passed Pre-Filter"

    # -------------------------------------------------------------------------
    # קליטת נרות ועיבוד אסינכרוני
    # -------------------------------------------------------------------------
    async def on_minute_bar(self, bar) -> None:
        """Callback שרץ מיידית בעת סגירת נר דקה ב-IEX."""
        symbol = bar.symbol
        candle_ts = str(bar.timestamp)

        candle = {
            "ticker": symbol,
            "timeframe": "1m",
            "timestamp": candle_ts,
            "open": float(bar.open),
            "high": float(bar.high),
            "low": float(bar.low),
            "close": float(bar.close),
            "volume": float(bar.volume),
        }

        # 1. עדכון RAM מיידי
        self.memory_buffers[symbol].append(candle)
        buffer_len = len(self.memory_buffers[symbol])

        logger.info(
            f"⚡ [{symbol}] Live Bar Received @ {candle_ts} | Close: ${candle['close']:.2f}"
        )

        # 2. שמירת הנר הגולמי ל-SQLite
        self._persist_candle_to_db(candle)

        # 3. בדיקת כמות נרות מינימלית לחישוב אינדיקטורים
        if buffer_len < 15:
            logger.info(f"⏳ [{symbol}] Accumulating RAM buffer ({buffer_len}/15)...")
            return

        # 4. חישוב נתוני 1m מהירים ב-RAM (הפרדה לשתי שורות למניעת AttributeError)
        df_1m = pd.DataFrame(list(self.memory_buffers[symbol]))
        proc_1m = DataProcessor(df_1m)
        proc_1m.calculate_indicators()
        trigger_summary = proc_1m.get_latest_summary()

        # 5. בדיקת מתג ה-AI מתוך ממשק ה-Streamlit
        if not self._is_ai_enabled():
            logger.info(f"⏸️ [{symbol}] AI Evaluation paused via UI switch.")
            return

        # 6. בדיקת Pre-Filter מתמטית ב-RAM
        passed, filter_reason = self.passes_pre_filter(trigger_summary)
        if not passed:
            logger.info(f"🤖 [{symbol}] Decision: HOLD (Confidence: 0.0) | Latency: 0.7ms | {filter_reason}")
            filter_decision = {
                "timestamp": candle_ts,
                "action": "HOLD",
                "confidence": 0.0,
                "entry_price": 0.0,
                "stop_loss": 0.0,
                "take_profit": 0.0,
                "reasoning": f"Filtered: {filter_reason}",
            }
            self._log_decision_to_db(symbol, filter_decision, candle_timestamp=candle_ts, status="SUCCESS")
            return

        # 7. בדיקת שכבת הסיכונים (Hard Risk Guard)
        allowed, risk_reason = self.risk_guard.can_open_trade(symbol)
        if not allowed:
            logger.info(f"🛑 [{symbol}] Risk Guard Block: {risk_reason}")
            guard_decision = {
                "timestamp": candle_ts,
                "action": "HOLD",
                "confidence": 0.0,
                "entry_price": 0.0,
                "stop_loss": 0.0,
                "take_profit": 0.0,
                "reasoning": f"Blocked by Risk Guard: {risk_reason}",
            }
            self._log_decision_to_db(symbol, guard_decision, candle_timestamp=candle_ts, status="SUCCESS")
            return

        # 8. שיגור משימת ה-AI ברקע ללא חסימת ה-WebSocket
        if self.orchestrator:
            asyncio.create_task(
                self._async_evaluate(symbol, candle, trigger_summary)
            )

    async def _async_evaluate(
        self, symbol: str, latest_candle: dict, trigger_summary: dict
    ) -> None:
        """ריצת מפל הסוכנים ברקע ושיגור פקודות."""
        candle_ts = latest_candle.get("timestamp") or str(datetime.now(timezone.utc))
        start_time = asyncio.get_event_loop().time()

        try:
            # שליפת 15m ו-1D מ-SQL
            df_15m = self.loader.query_candles(symbol=symbol, timeframe="15m", limit=60, ascending=True)
            df_1d = self.loader.query_candles(symbol=symbol, timeframe="1D", limit=120, ascending=True)

            # Resampling מקומי מ-RAM אם טרם סונכרנו נרות 15m
            if df_15m.empty:
                df_1m_mem = pd.DataFrame(list(self.memory_buffers[symbol]))
                df_15m = DataProcessor.resample_1m_to_15m(df_1m_mem)

            # חישוב תמציות מאקרו ומבנה
            if not df_1d.empty:
                proc_1d = DataProcessor(df_1d)
                proc_1d.calculate_indicators()
                macro_summary = proc_1d.get_latest_summary()
            else:
                macro_summary = trigger_summary

            if not df_15m.empty:
                proc_15m = DataProcessor(df_15m)
                proc_15m.calculate_indicators()
                structure_summary = proc_15m.get_latest_summary()
            else:
                structure_summary = trigger_summary

            data_bundle = {
                "macro": macro_summary,
                "structure": structure_summary,
                "trigger": trigger_summary,
            }

            # הרצת תזמורת הסוכנים ב-Threadpool
            decision = await asyncio.to_thread(
                self.orchestrator.evaluate_symbol,
                symbol=symbol,
                data_bundle=data_bundle,
            )

            latency_ms = (asyncio.get_event_loop().time() - start_time) * 1000
            action = decision.get("action", "HOLD")
            confidence = float(decision.get("confidence", 0.0))

            logger.info(
                f"🤖 [{symbol}] Decision: {action} (Confidence: {confidence}) | Latency: {latency_ms:.1f}ms"
            )

            # הבטחת חותמת הזמן בהחלטה
            decision["timestamp"] = candle_ts
            self._log_decision_to_db(symbol, decision, candle_timestamp=candle_ts, status="SUCCESS")

            # שיגור פקודת מסחר אם התקבל איתות כניסה
            if action in ["BUY", "SELL"]:
                logger.info(
                    f"🎯 LIVE SIGNAL: {action} {symbol} @ {decision.get('entry_price', 0.0):.2f} | "
                    f"SL: {decision.get('stop_loss', 0.0):.2f} | TP: {decision.get('take_profit', 0.0):.2f}"
                )
                try:
                    order = self.executor.submit_bracket_order(decision)
                    if order:
                        logger.info(f"✅ Bracket Order successfully submitted for {symbol}!")
                except Exception as ex:
                    logger.error(f"Failed to submit bracket order: {ex}")

        except Exception as e:
            logger.warning(f"⚠️ AI Evaluation failed for {symbol}: {e}")
            fallback_decision = {
                "timestamp": candle_ts,
                "action": "HOLD",
                "confidence": 0.0,
                "entry_price": 0.0,
                "stop_loss": 0.0,
                "take_profit": 0.0,
                "reasoning": f"AI Fallback / Error: {str(e)[:80]}",
            }
            self._log_decision_to_db(
                symbol,
                fallback_decision,
                candle_timestamp=candle_ts,
                status="ERROR",
                error_msg=str(e),
            )

    # -------------------------------------------------------------------------
    # כתיבה ל-SQLite
    # -------------------------------------------------------------------------
    def _persist_candle_to_db(self, candle: dict) -> None:
        """שמירה של נר הדקה ישירות ל-SQLite."""
        try:
            with sqlite3.connect(self.config.DB_PATH, timeout=10.0) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO candles (
                        ticker, timeframe, timestamp, open, high, low, close, volume
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    candle["ticker"],
                    candle["timeframe"],
                    str(candle["timestamp"]),
                    candle["open"],
                    candle["high"],
                    candle["low"],
                    candle["close"],
                    candle["volume"],
                ))
        except Exception as e:
            logger.error(f"Failed to persist candle to DB: {e}")

    def _log_decision_to_db(
        self,
        symbol: str,
        decision: dict,
        candle_timestamp: Optional[str] = None,
        status: str = "SUCCESS",
        error_msg: Optional[str] = None,
    ) -> None:
        """שמירת החלטת AI / סינון / שגיאה ב-SQLite עם חותמת זמן מובטחת."""
        ts = decision.get("timestamp") or candle_timestamp or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        query = """
            INSERT INTO ai_decisions (
                timestamp, symbol, action, confidence, 
                entry_price, stop_loss, take_profit, 
                reasoning, status, error_msg
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        try:
            with sqlite3.connect(self.config.DB_PATH, timeout=10.0) as conn:
                conn.execute(
                    query,
                    (
                        str(ts),
                        symbol,
                        decision.get("action", "HOLD"),
                        float(decision.get("confidence", 0.0)),
                        float(decision.get("entry_price", 0.0)),
                        float(decision.get("stop_loss", 0.0)),
                        float(decision.get("take_profit", 0.0)),
                        decision.get("reasoning", ""),
                        status,
                        error_msg,
                    ),
                )
        except Exception as e:
            logger.error(f"Failed to log AI decision to DB: {e}")

    # -------------------------------------------------------------------------
    # הפעלה
    # -------------------------------------------------------------------------
    def start(self) -> None:
        """הפעלת סטרים ה-WebSocket של Alpaca."""
        logger.info(
            f"🚀 Starting Live IEX Engine for symbols: {self.symbols} (Real-time 0s delay)..."
        )
        self.stream.subscribe_bars(self.on_minute_bar, *self.symbols)
        self.stream.run()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    engine = LiveIEXTraderEngine(symbols=["NVDA", "TSLA", "AAPL"])
    engine.start()