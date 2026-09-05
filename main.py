
import logging
import sys
from typing import Any, Dict, Optional, Tuple
import pandas as pd

# local modules
from alpaca.data.timeframe import TimeFrame
#from agents.orchestrator import TradingOrchestrator
from config import Config
from src.data_loader import DataLoader
from src.processor import DataProcessor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

def process_market_slice(df_raw: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """צינור עיבוד נתונים ב-RAM."""
    processor = DataProcessor(df_raw)

    # 1. חישוב כל האינדיקטורים והחזרת DF מלא
    enriched_df = processor.calculate_indicators()

    # 2. חילוץ תקציר הנר האחרון ל-AI
    summary_payload = processor.get_latest_summary()

    return enriched_df, summary_payload

def run_data_pipeline(symbol: str) -> dict:
    """Data pipeline: load -> save -> fetch -> calculate inside the RAM"""
    config = Config()
    loader = DataLoader(api_key=config.ALPACA_KEY, secret_key=config.ALPACA_SECRET, db_path=config.DB_PATH)

    logger.info(f"Running data pipeline for {symbol}...")

    # 1. משיכת נרות 1 דקה אחרונים ושמירה ב-DB
    raw_bars = loader.fetch_historical_bars(symbol, timeframe=TimeFrame.Minute, timeframe_str="1m", days_back=2)
    loader.save_to_db(raw_bars)

    # 2. שליפת חלון הנתונים הרלוונטי מה-DB
    df_1m = loader.load_from_db(symbol=symbol, timeframe_str="1m")

    # 3. העברה למנוע החישוב ב-RAM (ללא כתיבת אינדיקטורים ל-DB)
    processed_features = calculate_indicators(df_1m)

    logger.info(f"Pipeline ready: {len(df_1m)} candles loaded.")
    return processed_features

def main():

    try:
        run_data_pipeline("AAPL")
        return 0
    except KeyboardInterrupt:
        logger.warning("Execution interrupted by user.")
        return 130
    except Exception as e:
        logger.exception(f"Fatal error during execution: {e}")
        return 1


if __name__ == '__main__':
    sys.exit(main())
