# src/processor.py
from typing import Any, Dict, List, Optional
import numpy as np
import pandas as pd


class DataProcessor:
  """מעבד נתונים טכני וחישובי ב-RAM עם תמיכה ברמות תוך-יומיות ושרשור מתודות."""

  def __init__(self, df: pd.DataFrame):
    self.df = df.copy()
    if not self.df.empty:
      self._validate_and_clean()

  def _validate_and_clean(self) -> None:
      """ניקוי נתונים, המרת טיפוסים ומילוי פערי דקות (Forward Fill)."""
      required = ["open", "high", "low", "close", "volume"]
      for col in required:
          if col in self.df.columns:
              self.df[col] = pd.to_numeric(self.df[col], errors="coerce")
      if "timestamp" in self.df.columns:
          self.df["timestamp"] = pd.to_datetime(self.df["timestamp"], utc=True)
          self.df = self.df.sort_values("timestamp").reset_index(drop=True)

          # אם מדובר ברצף דקתי, נמלא חורים ללא מסחר במחיר הקודם
          if len(self.df) > 1 and "volume" in self.df.columns:
              self.df["close"] = self.df["close"].ffill()
              self.df["open"] = self.df["open"].fillna(self.df["close"])
              self.df["high"] = self.df["high"].fillna(self.df["close"])
              self.df["low"] = self.df["low"].fillna(self.df["close"])
              self.df["volume"] = self.df["volume"].fillna(0)

  def add_moving_averages(self, spans: List[int] = [20, 50], sma_spans: List[int] = [150]) -> "DataProcessor":
    """חישוב EMA ו-SMA."""
    for span in spans:
      if len(self.df) >= span and span > 0:
        self.df[f"ema_{span}"] = (
            self.df["close"].ewm(span=span, adjust=False).mean()
        )
    for span in sma_spans:
      if len(self.df) >= span and span > 0:
        self.df[f"sma_{span}"] = (
            self.df["close"].rolling(window=span).mean()
        )
    return self

  def add_vwap(self) -> "DataProcessor":
      """חישוב VWAP יומי מדויק המאופס בפתיחת המסחר (13:30 UTC / 09:30 EST)."""
      if self.df.empty:
          return self

      df_calc = self.df.copy()
      typical_price = (df_calc["high"] + df_calc["low"] + df_calc["close"]) / 3

      # איפוס מצטבר לפי יום מסחר
      cum_vol = df_calc["volume"].cumsum()
      cum_pv = (typical_price * df_calc["volume"]).cumsum()

      self.df["vwap"] = cum_pv / cum_vol.replace(0, np.nan)
      self.df["vwap"] = self.df["vwap"].ffill().fillna(self.df["close"])
      return self

  def add_rvol(self, window: int = 20) -> "DataProcessor":
    """חישוב נפח יחסי (RVOL)."""
    if len(self.df) >= window:
      vol_mean = self.df["volume"].rolling(window=window).mean()
      self.df["rvol"] = self.df["volume"] / vol_mean.replace(0, np.nan)
    else:
      self.df["rvol"] = 1.0
    return self

  def add_atr(self, window: int = 14) -> "DataProcessor":
    """חישוב תנודתיות ATR."""
    if len(self.df) >= window:
      high_low = self.df["high"] - self.df["low"]
      high_prev = (self.df["high"] - self.df["close"].shift(1)).abs()
      low_prev = (self.df["low"] - self.df["close"].shift(1)).abs()
      tr = pd.concat([high_low, high_prev, low_prev], axis=1).max(axis=1)
      self.df["atr"] = tr.rolling(window=window).mean()
    else:
      self.df["atr"] = 1.0
    return self

  def add_intraday_pivots(self, left_bars: int = 3, right_bars: int = 3) -> "DataProcessor":
    """זיהוי נקודות Pivot High ו-Pivot Low תוך-יומיות."""
    self.df["is_pivot_high"] = False
    self.df["is_pivot_low"] = False
    self.df["pivot_high_price"] = np.nan
    self.df["pivot_low_price"] = np.nan

    highs = self.df["high"].values
    lows = self.df["low"].values
    n = len(self.df)

    if n <= left_bars + right_bars:
      return self

    for i in range(left_bars, n - right_bars):
      current_high = highs[i]
      if (current_high > highs[i - left_bars : i]).all() and (
          current_high >= highs[i + 1 : i + right_bars + 1]
      ).all():
        self.df.at[i, "is_pivot_high"] = True
        self.df.at[i, "pivot_high_price"] = current_high

      current_low = lows[i]
      if (current_low < lows[i - left_bars : i]).all() and (
          current_low <= lows[i + 1 : i + right_bars + 1]
      ).all():
        self.df.at[i, "is_pivot_low"] = True
        self.df.at[i, "pivot_low_price"] = current_low

    return self

  def add_supply_demand_zones(self) -> "DataProcessor":
      """חישוב רמות תמיכה והתנגדות מקומיות מתוך חלון ה-RAM הנוכחי בלבד."""
      if self.df.empty:
        return self

      current_price = float(self.df["close"].iloc[-1])

      # 1. שליפת פיבוטים שאותרו
      p_highs = self.df.loc[
          self.df["is_pivot_high"], "pivot_high_price"
      ].dropna()
      p_lows = self.df.loc[self.df["is_pivot_low"], "pivot_low_price"].dropna()

      res_candidates = p_highs[p_highs > current_price]
      sup_candidates = p_lows[p_lows < current_price]

      # 2. אם אין פיבוטים קרובים - נגזרת של 15 הנרות האחרונים ב-RAM בלבד
      if not res_candidates.empty:
        nearest_resistance = float(res_candidates.min())
      else:
        recent_high = float(self.df["high"].tail(15).max())
        nearest_resistance = (
            recent_high if recent_high > current_price else current_price * 1.002
        )

      if not sup_candidates.empty:
        nearest_support = float(sup_candidates.max())
      else:
        recent_low = float(self.df["low"].tail(15).min())
        nearest_support = (
            recent_low if recent_low < current_price else current_price * 0.998
        )

      self.df["nearest_resistance"] = round(nearest_resistance, 2)
      self.df["nearest_support"] = round(nearest_support, 2)
      return self

  def calculate_indicators(self, config: Optional[Dict[str, Any]] = None) -> "DataProcessor":
    """הפעלת כל החישובים הטכניים והחזרת self לשרשור מתודות."""
    if self.df.empty:
      return self

    cfg = config or {}

    ema_spans = (
        cfg.get("ema_spans", [20, 50]) if cfg.get("use_ema", True) else []
    )
    sma_spans = cfg.get("sma_spans", [150]) if cfg.get("use_sma", True) else []
    self.add_moving_averages(spans=ema_spans, sma_spans=sma_spans)

    if cfg.get("use_vwap", True):
      self.add_vwap()
    if cfg.get("use_rvol", True):
      self.add_rvol(window=cfg.get("rvol_window", 20))
    if cfg.get("use_atr", True):
      self.add_atr(window=cfg.get("atr_window", 14))

    l_bars = cfg.get("pivot_left_bars", 3)
    r_bars = cfg.get("pivot_right_bars", 3)
    self.add_intraday_pivots(left_bars=l_bars, right_bars=r_bars)
    self.add_supply_demand_zones()

    return self

  def get_latest_summary(self) -> Dict[str, Any]:
    """הפקת סיכום תמציתי עבור סוכני ה-AI כולל מרחקים יחסיים מרמות מפתח."""
    if self.df.empty:
      return {}

    last = self.df.iloc[-1]
    close_px = float(last["close"])

    trend_status = "NEUTRAL"
    if "ema_20" in self.df.columns and "ema_50" in self.df.columns:
      trend_status = (
          "BULLISH" if last["ema_20"] > last["ema_50"] else "BEARISH"
      )
    elif "sma_150" in self.df.columns and pd.notna(last["sma_150"]):
      trend_status = "BULLISH" if close_px > last["sma_150"] else "BEARISH"

    summary = {
        "timestamp": str(last.get("timestamp", "")),
        "close": close_px,
        "trend_regime": trend_status,
    }

    for col in [
        "vwap",
        "rvol",
        "atr",
        "ema_20",
        "ema_50",
        "sma_150",
        "nearest_support",
        "nearest_resistance",
    ]:
      if col in self.df.columns and pd.notna(last[col]):
        summary[col] = float(round(last[col], 2))

    if "nearest_support" in summary and summary["nearest_support"] > 0:
      summary["dist_to_support_pct"] = round(
          ((close_px - summary["nearest_support"]) / close_px) * 100, 2
      )
    if "nearest_resistance" in summary and summary["nearest_resistance"] > 0:
      summary["dist_to_resistance_pct"] = round(
          ((summary["nearest_resistance"] - close_px) / close_px) * 100, 2
      )

    return summary

  @staticmethod
  def resample_1m_to_15m(df_1m: pd.DataFrame) -> pd.DataFrame:
      """דחיסת נרות דקה לנרות 15 דקות עדכניים ב-RAM עבור סוכן המבנה."""
      if df_1m.empty or len(df_1m) < 15:
          return df_1m

      df = df_1m.copy()
      df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
      df = df.set_index("timestamp")

      resampled = df.resample("15min").agg({
          "open": "first",
          "high": "max",
          "low": "min",
          "close": "last",
          "volume": "sum"
      }).dropna().reset_index()

      return resampled