# src/live_stream_engine.py
import asyncio
from collections import deque
from datetime import datetime, timezone
import logging
import os
import sqlite3
import sys
from typing import List, Optional

# וידוא נתיב הפרויקט הראשי ב-sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from alpaca.data.enums import DataFeed
from alpaca.data.live.stock import StockDataStream
import pandas as pd

from agents.orchestrator import TradingOrchestrator
from config import Config
from src.data_loader import DataLoader
from src.processor import DataProcessor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("LiveEngine")


class LiveIEXTraderEngine:
  """מנוע מסחר Live בזמן אמת (Alpaca IEX WebSocket).

  מבצע שמירת נרות מידית ל-SQLite, חישובי RAM אסינכרוניים,
  והפעלת תזמורת ה-AI ללא חסימת ה-WebSocket.
  """

  def __init__(self, symbols: Optional[List[str]] = None):
    self.config = Config()
    self.symbols = symbols or self.config.WATCHLIST[:3]

    # 1. אתחול מנהל נתונים ותזמורת הסוכנים
    self.loader = DataLoader(
        api_key=self.config.ALPACA_KEY,
        secret_key=self.config.ALPACA_SECRET,
        db_path=self.config.DB_PATH,
    )
    self.orchestrator = TradingOrchestrator(
        api_key=self.config.GEMINI_API_KEY,
        model_name=self.config.GEMINI_MODEL,
    )

    # 2. אתחול ה-WebSocket החינמי של IEX
    self.stream = StockDataStream(
        api_key=self.config.ALPACA_KEY,
        secret_key=self.config.ALPACA_SECRET,
        feed=DataFeed.IEX,
        raw_data=False,
    )

    # 3. ניהול RAM מהיר: חלון מתגלגל של 60 נרות לכל מניה
    self.memory_buffers = {s: deque(maxlen=60) for s in self.symbols}

    # 4. הכנת מסד הנתונים וטעינת נרות היסטוריים ל-RAM
    self._init_decisions_table()
    self._seed_ram_from_db()

  def _init_decisions_table(self) -> None:
    """יצירת טבלת ai_decisions במידה ואינה קיימת."""
    with sqlite3.connect(self.config.DB_PATH) as conn:
      conn.execute("""
                CREATE TABLE IF NOT EXISTS ai_decisions (
                    timestamp DATETIME,
                    symbol TEXT,
                    action TEXT,
                    confidence REAL,
                    entry_price REAL,
                    stop_loss REAL,
                    take_profit REAL,
                    reasoning TEXT
                );
            """)

  def _seed_ram_from_db(self) -> None:
    """טעינת היסטוריית 1m אחרונה מה-SQL ל-RAM."""
    logger.info("🧠 Seeding RAM buffers from SQLite candles...")
    for symbol in self.symbols:
      recent_df = self.loader.query_candles(
          symbol=symbol,
          timeframe="1m",
          limit=60,
          ascending=True,
      )
      if not recent_df.empty:
        for _, row in recent_df.iterrows():
          self.memory_buffers[symbol].append({
              "ticker": symbol,
              "timeframe": "1m",
              "timestamp": str(row["timestamp"]),
              "open": float(row["open"]),
              "high": float(row["high"]),
              "low": float(row["low"]),
              "close": float(row["close"]),
              "volume": float(row["volume"]),
          })
        logger.info(
            f"   ↳ [{symbol}] Loaded {len(self.memory_buffers[symbol])} bars"
            " into RAM."
        )

  def _persist_candle_to_db(self, candle: dict) -> None:
    """שמירת נר בודד ישירות לטבלת candles ב-SQLite באופן בטוח."""
    query = """
        INSERT OR REPLACE INTO candles (ticker, timeframe, timestamp, open, high, low, close, volume)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
    try:
      with sqlite3.connect(self.config.DB_PATH) as conn:
        conn.execute(
            query,(
                candle.get("ticker"),
                candle.get("timeframe", "1m"),
                candle.get("timestamp"),
                candle.get("open"),
                candle.get("high"),
                candle.get("low"),
                candle.get("close"),
                candle.get("volume"),
            ),
        )
    except Exception as e:
      logger.error(
          f"Failed to persist candle to SQLite for {candle.get('ticker')}: {e}"
      )

  def _log_decision_to_db(self, symbol: str, decision: dict) -> None:
    """שמירת החלטת התזמורת למסד הנתונים להצגה ב-Streamlit."""
    try:
      with sqlite3.connect(self.config.DB_PATH) as conn:
        conn.execute(
            """
                    INSERT INTO ai_decisions (
                        timestamp, symbol, action, confidence, 
                        entry_price, stop_loss, take_profit, reasoning
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
            (
                datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                symbol,
                decision.get("action", "HOLD"),
                decision.get("confidence", 0.0),
                decision.get("entry_price", 0.0),
                decision.get("stop_loss", 0.0),
                decision.get("take_profit", 0.0),
                decision.get("reasoning", ""),
            ),
        )
    except Exception as e:
      logger.error(f"Failed to log decision to DB for {symbol}: {e}")

  async def on_minute_bar(self, bar) -> None:
      symbol = bar.symbol

      candle = {
          "ticker": symbol,
          "timeframe": "1m",
          "timestamp": str(bar.timestamp),
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
          f"⚡ [{symbol}] Live Bar Received @ {candle['timestamp']} | Close:"
          f" ${candle['close']:.2f}"
      )

      # 2. שמירה ישירה ל-DB (בטוחה ומיידית)
      self._persist_candle_to_db(candle)

      # 3. בדיקה האם המשתמש כיבה את ה-AI מתוך Streamlit
      if not self._is_ai_enabled():
        logger.info(
            f"⏸️ [{symbol}] AI Evaluation Disabled via UI. Streaming and saving"
            " only."
        )
        return

      # 4. בדיקת מינימום נרות ב-RAM ושיגור ניתוח AI ברקע
      if buffer_len < 15: # change to lower, 5 maybe?
        logger.info(
            f"⏳ [{symbol}] Accumulating RAM buffer ({buffer_len}/15)..."
        )
        return

      if self.orchestrator:
        asyncio.create_task(self._async_evaluate(symbol, candle))

  async def _async_evaluate(self, symbol: str, latest_candle: dict) -> None:
      """
      הרצת מפל הסוכנים (Waterfall) כמשימת רקע אסינכרונית,
      עיבוד מסגרות זמן רב-שכבתיות, אכיפת שכבת סיכונים ושמירת תוצאות ב-DB.
      """
      try:
          # -------------------------------------------------------------
          # א. עיבוד נתוני 1m מה-RAM עבור סוכן הטריגר (Trigger Agent)
          # -------------------------------------------------------------
          df_1m = pd.DataFrame(list(self.memory_buffers[symbol]))
          proc_1m = DataProcessor(df_1m)
          proc_1m.calculate_indicators()
          trigger_summary = proc_1m.get_latest_summary()

          # -------------------------------------------------------------
          # ב. הפקת / שליפת נתוני 15m עבור סוכן המבנה (Structure Agent)
          # -------------------------------------------------------------
          # ניסיון לבצע Resampling מתוך נרות ה-1m המעודכנים ב-RAM
          if hasattr(DataProcessor, "resample_1m_to_15m") and len(df_1m) >= 15:
              df_15m = DataProcessor.resample_1m_to_15m(df_1m)
          else:
              df_15m = self.loader.query_candles(
                  symbol=symbol,
                  timeframe="15m",
                  limit=60,
                  ascending=True
              )

          if not df_15m.empty:
              proc_15m = DataProcessor(df_15m)
              proc_15m.calculate_indicators()
              structure_summary = proc_15m.get_latest_summary()
          else:
              structure_summary = trigger_summary

          # -------------------------------------------------------------
          # ג. שליפת נתוני 1D מה-SQL עבור סוכן המאקרו (Macro Agent)
          # -------------------------------------------------------------
          df_1d = self.loader.query_candles(
              symbol=symbol,
              timeframe="1D",
              limit=60,
              ascending=True
          )
          if not df_1d.empty:
              proc_1d = DataProcessor(df_1d)
              proc_1d.calculate_indicators()
              macro_summary = proc_1d.get_latest_summary()
          else:
              macro_summary = structure_summary

          # -------------------------------------------------------------
          # ד. הרכבת חבילת הנתונים המלאה (Multi-Timeframe Data Bundle)
          # -------------------------------------------------------------
          data_bundle = {
              "macro": macro_summary,
              "structure": structure_summary,
              "trigger": trigger_summary
          }

          start_time = asyncio.get_event_loop().time()

          # -------------------------------------------------------------
          # ה. הפעלת תזמורת הסוכנים (Orchestrator Waterfall)
          # -------------------------------------------------------------
          # במקום קריאה ישירה:
          # decision = self.orchestrator.evaluate_symbol(symbol=symbol, data_bundle=data_bundle)

          # עדיף להריץ ב-Threadpool אסינכרוני:
          decision = await asyncio.to_thread(
              self.orchestrator.evaluate_symbol,
              symbol=symbol,
              data_bundle=data_bundle
          )

          latency_ms = (asyncio.get_event_loop().time() - start_time) * 1000
          action = decision.get("action", "HOLD")

          logger.info(
              f"🤖 [{symbol}] Decision: {action} "
              f"(Confidence: {decision.get('confidence', 0.0)}) | Latency: {latency_ms:.1f}ms"
          )

          # -------------------------------------------------------------
          # ו. רישום ההחלטה למסד הנתונים עבור Streamlit
          # -------------------------------------------------------------
          self._log_decision_to_db(symbol, decision)

          # -------------------------------------------------------------
          # ז. טיפול באיתות כניסה (BUY / SELL)
          # -------------------------------------------------------------
          if action in ["BUY", "SELL"]:
              entry_px = decision.get("entry_price", latest_candle.get("close", 0.0))
              sl_px = decision.get("stop_loss", 0.0)
              tp_px = decision.get("take_profit", 0.0)

              logger.info(
                  f"🎯 LIVE SIGNAL: {action} {symbol} @ ${entry_px:.2f} | "
                  f"SL: ${sl_px:.2f} | TP: ${tp_px:.2f}"
              )

      except Exception as e:
          logger.warning(
              f"⚠️ AI evaluation failed for {symbol} (Model busy/503/429/Parsing): {e}"
          )
          fallback_decision = {
              "action": "HOLD",
              "confidence": 0.0,
              "entry_price": 0.0,
              "stop_loss": 0.0,
              "take_profit": 0.0,
              "reasoning": f"AI Temporarily Unavailable: {str(e)[:70]}"
          }
          self._log_decision_to_db(symbol, fallback_decision)

  def start(self) -> None:
    """הפעלת הזרמת ה-WebSocket של Alpaca IEX."""
    logger.info(f"🚀 Starting Live IEX Engine for: {self.symbols}")
    logger.info("📡 Listening for real-time minute bars (0s delay)...")
    self.stream.subscribe_bars(self.on_minute_bar, *self.symbols)
    self.stream.run()

  def _is_ai_enabled(self) -> bool:
      """בדיקה דינמית מול טבלת system_settings ב-SQLite האם ה-AI פעיל"""
      try:
          with sqlite3.connect(self.config.DB_PATH) as conn:
              res = conn.execute(
                  "SELECT value FROM system_settings WHERE"
                  " key='ai_evaluation_enabled'"
              ).fetchone()
              return res[0] == "true" if res else True
      except Exception:
          return True




if __name__ == "__main__":
  engine = LiveIEXTraderEngine(symbols=["NVDA", "TSLA", "AAPL"])
  engine.start()