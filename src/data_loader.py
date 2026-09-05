import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
import pandas as pd
from alpaca.data.enums import DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit


class DataLoader:
    """שכבת ניהול נתונים: סנכרון מאלפקא, Resampling מקומי ושליפה מהירה מ-SQLite."""

    def __init__(self, api_key: str, secret_key: str, db_path: str = "market_data.db"):
        self.client = StockHistoricalDataClient(api_key, secret_key)
        self.db_path = db_path
        self.init_db()

    def init_db(self) -> None:
        """יצירת טבלאות, אינדקסים והפעלת מצב WAL למניעת נעילות מקביליות."""
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA busy_timeout=5000;")
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
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_query 
                ON candles (ticker, timeframe, timestamp);
            """)

    def get_last_candle_time(self, symbol: str, timeframe_str: str) -> Optional[datetime]:
        """שליפת התאריך והשעה של הנר האחרון שקיים במסד הנתונים."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT MAX(timestamp) FROM candles 
                WHERE ticker = ? AND timeframe = ?
                """,
                (symbol, timeframe_str),
            )
            res = cursor.fetchone()[0]
            if res:
                dt = datetime.fromisoformat(res)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            return None

    def sync_symbol_data(self, symbol: str, timeframe_str: str, alpaca_tf: TimeFrame, default_days_back: int,) -> int:
        """סנכרון דלתא עד הרגע האחרון מול Alpaca ושמירה ב-SQL."""
        last_dt = self.get_last_candle_time(symbol, timeframe_str)
        now_utc = datetime.now(timezone.utc)
        end_dt = now_utc - timedelta(minutes=15)

        if last_dt:
            start_dt = last_dt
        else:
            start_dt = now_utc - timedelta(days=default_days_back)

        if start_dt >= end_dt:
            return 0

        if (end_dt - start_dt).total_seconds() < 60 and timeframe_str == "1m":
            return 0

        req = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=alpaca_tf,
            start=start_dt,
            end=end_dt,
            feed=DataFeed.IEX,
        )
        bars = self.client.get_stock_bars(req)
        df = bars.df

        if df.empty:
            return 0

        df = df.reset_index()
        df["ticker"] = symbol
        df["timeframe"] = timeframe_str
        df["timestamp"] = df["timestamp"].astype(str)
        clean_df = df[["ticker", "timeframe", "timestamp", "open", "high", "low", "close", "volume"]]

        with sqlite3.connect(self.db_path) as conn:
            clean_df.to_sql("temp_candles", conn, if_exists="replace", index=False)
            cursor = conn.execute("""
                INSERT OR REPLACE INTO candles 
                SELECT * FROM temp_candles;
            """)
            conn.execute("DROP TABLE temp_candles;")
            return cursor.rowcount

    def generate_resampled_timeframes(self, symbol: str) -> Dict[str, int]:
        """בניית נרות 5m, 15m, 1H ישירות מנתוני ה-1m המקומיים לחיסכון של 80% בקריאות API."""
        df_1m = self.query_candles(symbol, "1m", limit=50000, ascending=True)
        if df_1m.empty:
            return {}

        df_1m["dt"] = pd.to_datetime(df_1m["timestamp"])
        df_1m = df_1m.set_index("dt")

        resample_rules = {
            "5m": "5min",
            "15m": "15min",
            "1H": "1h"
        }
        stats = {}

        for tf_name, rule in resample_rules.items():
            resampled = df_1m.resample(rule).agg({
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum"
            }).dropna().reset_index()

            resampled["ticker"] = symbol
            resampled["timeframe"] = tf_name
            resampled["timestamp"] = resampled["dt"].astype(str)
            clean_res = resampled[["ticker", "timeframe", "timestamp", "open", "high", "low", "close", "volume"]]

            with sqlite3.connect(self.db_path) as conn:
                clean_res.to_sql("temp_candles", conn, if_exists="replace", index=False)
                cursor = conn.execute("""
                    INSERT OR REPLACE INTO candles 
                    SELECT * FROM temp_candles;
                """)
                conn.execute("DROP TABLE temp_candles;")
                stats[tf_name] = cursor.rowcount

        return stats

    def query_candles(self,symbol: str,timeframe: str,start_date: Optional[str] = None,end_date: Optional[str] = None,
                        limit: Optional[int] = None,ascending: bool = True,) -> pd.DataFrame:
        """שליפת נרות גמישה מתוך ה-SQL."""
        query = """
            SELECT ticker, timeframe, timestamp, open, high, low, close, volume 
            FROM candles 
            WHERE ticker = ? AND timeframe = ?
        """
        params: List[Any] = [symbol, timeframe]

        if start_date:
            query += " AND timestamp >= ?"
            params.append(start_date)

        if end_date:
            query += " AND timestamp <= ?"
            params.append(end_date)

        order_dir = "ASC" if ascending else "DESC"
        query += f" ORDER BY timestamp {order_dir}"

        if limit:
            query += f" LIMIT {int(limit)}"

        with sqlite3.connect(self.db_path) as conn:
            df = pd.read_sql(query, conn, params=params)

        if not df.empty:
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            if not ascending:
                df = df.sort_values("timestamp", ascending=True).reset_index(drop=True)

        return df

    def get_multi_timeframe_slice(self, symbol: str, target_time: str) -> Dict[str, pd.DataFrame]:
        """שליפת כל מסגרות הזמן בדיוק עד דקת היעד ללא Lookahead Bias."""
        timeframes = {"1D": 250, "1H": 100, "15m": 60, "1m": 60}
        context = {}

        with sqlite3.connect(self.db_path) as conn:
            for tf, limit in timeframes.items():
                query = """
                    SELECT timestamp, open, high, low, close, volume 
                    FROM candles 
                    WHERE ticker = ? AND timeframe = ? AND timestamp <= ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                """
                df = pd.read_sql(query, conn, params=(symbol, tf, target_time, limit))
                if not df.empty:
                    df["timestamp"] = pd.to_datetime(df["timestamp"])
                    df = df.sort_values("timestamp", ascending=True).reset_index(drop=True)
                context[tf] = df

        return context

    def check_data_gaps(self, symbol: str, timeframe: str = "1m") -> List[Dict[str, Any]]:
        """זיהוי פערי זמן חריגים בתוך שעות מסחר רציפות."""
        query = """
            SELECT timestamp FROM candles 
            WHERE ticker = ? AND timeframe = ?
            ORDER BY timestamp ASC
        """
        with sqlite3.connect(self.db_path) as conn:
            df = pd.read_sql(query, conn, params=(symbol, timeframe))

        if df.empty or len(df) < 2:
            return []

        df["dt"] = pd.to_datetime(df["timestamp"])
        df["diff_minutes"] = df["dt"].diff().dt.total_seconds() / 60
        gaps = df[(df["diff_minutes"] > 1) & (df["diff_minutes"] < 300)]
        return gaps[["timestamp", "diff_minutes"]].to_dict(orient="records")

    def execute_raw_query(self, query: str, params: tuple = ()) -> tuple[pd.DataFrame, Optional[str]]:
        """הרצת שאילתת SQL חופשית."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                df = pd.read_sql(query, conn, params=params)
                return df, None
        except Exception as e:
            return pd.DataFrame(), str(e)

    def get_database_summary(self) -> pd.DataFrame:
        """סקירת כמות נרות וטווחי זמן במסד הנתונים."""
        query = """
            SELECT 
                ticker,
                timeframe,
                COUNT(*) as candle_count,
                MIN(timestamp) as first_candle,
                MAX(timestamp) as last_candle
            FROM candles
            GROUP BY ticker, timeframe
            ORDER BY ticker, timeframe;
        """
        with sqlite3.connect(self.db_path) as conn:
            return pd.read_sql(query, conn)

    def vacuum_db(self) -> None:
        """כיווץ ואופטימיזציה של קובץ ה-SQLite בדיסק."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("VACUUM;")

    def sync_today_intraday(self, symbol: str) -> int:
        """משיכת כל נרות ה-1m של יום המסחר הנוכחי החל מ-09:30 EST (13:30 UTC) ושמירתם ב-SQLite."""
        now_utc = datetime.now(timezone.utc)
        # הגדרת שעת פתיחת המסחר של היום ב-UTC (13:30 UTC = 09:30 EST)
        today_open_utc = now_utc.replace(
            hour=13, minute=30, second=0, microsecond=0
        )

        # אם השעה הנוכחית לפני שעת הפתיחה, מושכים מתחילת היום
        start_dt = (
            today_open_utc
            if now_utc > today_open_utc
            else now_utc - timedelta(hours=4)
        )

        req = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Minute,
            start=start_dt,
            end=now_utc,
            feed=DataFeed.IEX,
        )
        try:
            bars = self.client.get_stock_bars(req)
            df = bars.df
            if df.empty:
                return 0

            df = df.reset_index()
            df["ticker"] = symbol
            df["timeframe"] = "1m"
            df["timestamp"] = df["timestamp"].astype(str)
            clean_df = df[[
                "ticker",
                "timeframe",
                "timestamp",
                "open",
                "high",
                "low",
                "close",
                "volume",
            ]]

            with sqlite3.connect(self.db_path) as conn:
                clean_df.to_sql(
                    "temp_candles", conn, if_exists="replace", index=False
                )
                cursor = conn.execute("""
                      INSERT OR REPLACE INTO candles 
                      SELECT * FROM temp_candles;
                  """)
                conn.execute("DROP TABLE temp_candles;")
                return cursor.rowcount
        except Exception as e:
            print(f"Error syncing today intraday for {symbol}: {e}")
            return 0