"""DataProcessor: מנוע עיבוד טכני דטרמיניסטי ב-RAM (Zero Disk I/O).

משרת במקביל את סוכני ה-AI (JSON Payloads) ואת גרפי ה-Plotly ב-UI.
"""

from typing import Any, Dict, List, Optional
import numpy as np
import pandas as pd


class DataProcessor:
  """מעבד נתונים מתמטי ומבני לחילוץ אינדיקטורים ורמות שוק."""

  def __init__(self, df: pd.DataFrame):
    self.df = df.copy()
    if not self.df.empty:
      self._sanitize()

  def _sanitize(self) -> None:
    """ניקוי והמרת טיפוסי עמודות OHLCV וזמנים."""
    for col in ["open", "high", "low", "close", "volume"]:
      if col in self.df.columns:
        self.df[col] = pd.to_numeric(self.df[col], errors="coerce")
    if "timestamp" in self.df.columns:
      self.df["timestamp"] = pd.to_datetime(self.df["timestamp"])
      self.df = self.df.sort_values("timestamp").reset_index(drop=True)

  # =========================================================================
  # 1. CORE MATH & TECHNICAL INDICATORS (Method Chaining)
  # =========================================================================
  def add_moving_averages(
      self,
      sma_spans: Optional[List[int]] = None,
      ema_spans: Optional[List[int]] = None,
  ) -> "DataProcessor":
    """חישוב ממוצעים נעים פשוטים ומעריכיים."""
    for s in sma_spans or []:
      if len(self.df) >= s and s > 0:
        self.df[f"sma_{s}"] = self.df["close"].rolling(window=s).mean()
    for e in ema_spans or []:
      if len(self.df) >= e and e > 0:
        self.df[f"ema_{e}"] = (
            self.df["close"].ewm(span=e, adjust=False).mean()
        )
    return self

  def add_vwap(self) -> "DataProcessor":
    """חישוב VWAP תוך-יומי מצטבר."""
    if not self.df.empty:
      tp = (self.df["high"] + self.df["low"] + self.df["close"]) / 3
      cum_vol = self.df["volume"].cumsum()
      self.df["vwap"] = (tp * self.df["volume"]).cumsum() / cum_vol.replace(
          0, np.nan
      )
    return self

  def add_rvol(self, window: int = 20) -> "DataProcessor":
    """חישוב נפח מסחר יחסי (Relative Volume)."""
    if len(self.df) >= window:
      vol_mean = self.df["volume"].rolling(window=window).mean()
      self.df["rvol"] = self.df["volume"] / vol_mean.replace(0, np.nan)
    else:
      self.df["rvol"] = 1.0
    return self

  def add_atr(self, window: int = 14) -> "DataProcessor":
    """חישוב מדד תנודתיות Average True Range."""
    if len(self.df) >= window:
      hl = self.df["high"] - self.df["low"]
      hp = (self.df["high"] - self.df["close"].shift(1)).abs()
      lp = (self.df["low"] - self.df["close"].shift(1)).abs()
      tr = pd.concat([hl, hp, lp], axis=1).max(axis=1)
      self.df["atr"] = tr.rolling(window=window).mean()
    else:
      self.df["atr"] = 1.0
    return self

  def add_rsi(self, window: int = 14) -> "DataProcessor":
    """חישוב Relative Strength Index."""
    if len(self.df) >= window:
      delta = self.df["close"].diff()
      gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
      loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
      rs = gain / loss.replace(0, np.nan)
      self.df["rsi"] = 100 - (100 / (1 + rs))
    return self

  def add_pivots_and_zones(
      self, left_bars: int = 5, right_bars: int = 5
  ) -> "DataProcessor":
    """זיהוי Pivot High/Low וגזירת רמות תמיכה והתנגדות קרובות."""
    n = len(self.df)
    self.df["is_pivot_high"] = False
    self.df["is_pivot_low"] = False
    self.df["pivot_high_price"] = np.nan
    self.df["pivot_low_price"] = np.nan

    if n > left_bars + right_bars:
      highs = self.df["high"].values
      lows = self.df["low"].values
      for i in range(left_bars, n - right_bars):
        if (highs[i] > highs[i - left_bars : i]).all() and (
            highs[i] >= highs[i + 1 : i + right_bars + 1]
        ).all():
          self.df.at[i, "is_pivot_high"] = True
          self.df.at[i, "pivot_high_price"] = highs[i]

        if (lows[i] < lows[i - left_bars : i]).all() and (
            lows[i] <= lows[i + 1 : i + right_bars + 1]
        ).all():
          self.df.at[i, "is_pivot_low"] = True
          self.df.at[i, "pivot_low_price"] = lows[i]

    # חילוץ רמות S/R הקרובות למחיר הנוכחי
    if not self.df.empty:
      cp = float(self.df["close"].iloc[-1])
      p_highs = self.df.loc[
          self.df["is_pivot_high"], "pivot_high_price"
      ].dropna()
      p_lows = self.df.loc[self.df["is_pivot_low"], "pivot_low_price"].dropna()

      res_above = p_highs[p_highs > cp]
      nearest_res = (
          res_above.min()
          if not res_above.empty
          else (
              p_highs.iloc[-1]
              if not p_highs.empty
              else float(self.df["high"].tail(30).max())
          )
      )

      sup_below = p_lows[p_lows < cp]
      nearest_sup = (
          sup_below.max()
          if not sup_below.empty
          else (
              p_lows.iloc[-1]
              if not p_lows.empty
              else float(self.df["low"].tail(30).min())
          )
      )

      self.df["nearest_resistance"] = nearest_res
      self.df["nearest_support"] = nearest_sup
    return self

  # תאימות לאחור לקריאות בודדות
  def add_pivots(
      self, left_bars: int = 5, right_bars: int = 5
  ) -> "DataProcessor":
    return self.add_pivots_and_zones(
        left_bars=left_bars, right_bars=right_bars
    )

  def add_supply_demand_zones(self) -> "DataProcessor":
    return self

  # =========================================================================
  # 2. UI / PLOTLY / STREAMLIT CONNECTOR
  # =========================================================================
  def calculate_indicators(
      self, config: Optional[Dict[str, Any]] = None
  ) -> pd.DataFrame:
    """מתודה מרכזית לדפי Streamlit ו-Plotly (מחזירה תמיד pd.DataFrame)."""
    if self.df.empty:
      return self.df

    cfg = config or {}

    # ממוצעים
    sma_spans = (
        cfg.get("sma_spans", [150]) if cfg.get("use_sma", True) else []
    )
    ema_spans = (
        cfg.get("ema_spans", [20, 50]) if cfg.get("use_ema", True) else []
    )
    self.add_moving_averages(sma_spans=sma_spans, ema_spans=ema_spans)

    if cfg.get("use_vwap", True):
      self.add_vwap()
    if cfg.get("use_rvol", True):
      self.add_rvol(window=cfg.get("rvol_window", 20))
    if cfg.get("use_atr", True):
      self.add_atr(window=cfg.get("atr_window", 14))
    if cfg.get("use_rsi", False):
      self.add_rsi(window=cfg.get("rsi_window", 14))

    if (
        cfg.get("use_pivots", True)
        or cfg.get("use_zones", True)
        or cfg.get("use_sr", True)
    ):
      l_bars = cfg.get("pivot_left_bars", 5)
      r_bars = cfg.get("pivot_right_bars", 5)
      self.add_pivots_and_zones(left_bars=l_bars, right_bars=r_bars)

    return self.df

  # =========================================================================
  # 3. AI AGENT DEDICATED PAYLOADS & BUNDLER
  # =========================================================================
  def get_latest_summary(self) -> Dict[str, Any]:
    """סיכום כללי של הנר האחרון (משמש כ-Fallback או לתצוגת JSON מהירה)."""
    if self.df.empty:
      return {}

    last = self.df.iloc[-1]
    cp = float(last["close"])

    trend = "NEUTRAL"
    if "sma_150" in self.df.columns and pd.notna(last["sma_150"]):
      trend = "BULLISH" if cp > last["sma_150"] else "BEARISH"
    elif "ema_20" in self.df.columns and "ema_50" in self.df.columns:
      trend = "BULLISH" if last["ema_20"] > last["ema_50"] else "BEARISH"

    summary: Dict[str, Any] = {
        "timestamp": str(last.get("timestamp", "")),
        "close": cp,
        "trend_regime": trend,
    }

    for col in [
        "vwap",
        "rvol",
        "atr",
        "rsi",
        "nearest_support",
        "nearest_resistance",
    ]:
      if col in self.df.columns and pd.notna(last[col]):
        summary[col] = float(round(last[col], 2))

    for col in self.df.columns:
      if col.startswith(("ema_", "sma_")) and pd.notna(last[col]):
        summary[col] = float(round(last[col], 2))

    if summary.get("nearest_support", 0) > 0:
      summary["dist_to_support_pct"] = round(
          ((cp - summary["nearest_support"]) / cp) * 100, 2
      )
    if summary.get("nearest_resistance", 0) > 0:
      summary["dist_to_resistance_pct"] = round(
          ((summary["nearest_resistance"] - cp) / cp) * 100, 2
      )

    return summary

  @staticmethod
  def build_multi_agent_bundle(
      raw_dfs: Dict[str, pd.DataFrame], features_cfg: Dict[str, Any]
  ) -> Dict[str, Dict[str, Any]]:
    """חבילת נתונים מרכזית המפצלת ומזריקה לכל סוכן אך ורק את הנתונים שלו."""
    bundle: Dict[str, Dict[str, Any]] = {
        "macro": {},
        "structure": {},
        "trigger": {},
    }

    # 1. Macro (Daily / 4H)
    m_cfg = features_cfg.get("macro", {})
    m_tf = m_cfg.get("timeframe", "1D")
    df_m = raw_dfs.get(m_tf, pd.DataFrame())
    if not df_m.empty:
      proc_m = DataProcessor(df_m)
      smas = m_cfg.get("sma_spans", [150])
      emas = m_cfg.get("ema_spans", [])
      proc_m.add_moving_averages(sma_spans=smas, ema_spans=emas)
      if m_cfg.get("use_sr", True):
        proc_m.add_pivots_and_zones(5, 5)

      last_m = proc_m.df.iloc[-1]
      cp_m = float(last_m["close"])
      trend_ref = (
          last_m.get(f"sma_{smas[0]}")
          if smas
          else (last_m.get(f"ema_{emas[0]}") if emas else None)
      )

      bundle["macro"] = {
          "timestamp": str(last_m.get("timestamp", "")),
          "timeframe": m_tf,
          "close": cp_m,
          "trend_regime": (
              "BULLISH"
              if pd.notna(trend_ref) and cp_m > trend_ref
              else ("BEARISH" if pd.notna(trend_ref) else "NEUTRAL")
          ),
          "nearest_support": float(
              round(last_m.get("nearest_support", cp_m), 2)
          ),
          "nearest_resistance": float(
              round(last_m.get("nearest_resistance", cp_m), 2)
          ),
      }
      if pd.notna(trend_ref):
        bundle["macro"]["trend_line_val"] = float(round(trend_ref, 2))

    # 2. Structure (15m / 1H)
    s_cfg = features_cfg.get("structure", {})
    s_tf = s_cfg.get("timeframe", "15m")
    df_s = raw_dfs.get(s_tf, pd.DataFrame())
    if not df_s.empty:
      proc_s = DataProcessor(df_s)
      if s_cfg.get("use_atr", True):
        proc_s.add_atr(s_cfg.get("atr_window", 14))
      if s_cfg.get("use_pivots", True):
        proc_s.add_pivots_and_zones(
            s_cfg.get("pivot_left_bars", 5), s_cfg.get("pivot_right_bars", 5)
        )

      last_s = proc_s.df.iloc[-1]
      cp_s = float(last_s["close"])
      sup = float(last_s.get("nearest_support", cp_s))
      res = float(last_s.get("nearest_resistance", cp_s))

      bundle["structure"] = {
          "timestamp": str(last_s.get("timestamp", "")),
          "timeframe": s_tf,
          "close": cp_s,
          "nearest_support": sup,
          "nearest_resistance": res,
          "dist_to_support_pct": round(((cp_s - sup) / cp_s) * 100, 2)
          if sup > 0
          else 0.0,
          "dist_to_resistance_pct": round(((res - cp_s) / cp_s) * 100, 2)
          if res > 0
          else 0.0,
          "atr": float(round(last_s.get("atr", 1.0), 2)),
      }

    # 3. Trigger (1m / 5m)
    t_cfg = features_cfg.get("trigger", {})
    t_tf = t_cfg.get("timeframe", "1m")
    df_t = raw_dfs.get(t_tf, pd.DataFrame())
    if not df_t.empty:
      proc_t = DataProcessor(df_t)
      if t_cfg.get("use_vwap", True):
        proc_t.add_vwap()
      if t_cfg.get("use_rvol", True):
        proc_t.add_rvol(t_cfg.get("rvol_window", 20))
      emas_t = t_cfg.get("ema_spans", [20, 50])
      proc_t.add_moving_averages(ema_spans=emas_t).add_atr(14)

      last_t = proc_t.df.iloc[-1]
      cp_t = float(last_t["close"])
      vwap_v = float(last_t.get("vwap", cp_t))

      bundle["trigger"] = {
          "timestamp": str(last_t.get("timestamp", "")),
          "timeframe": t_tf,
          "close": cp_t,
          "vwap": round(vwap_v, 2),
          "price_vs_vwap": "ABOVE" if cp_t >= vwap_v else "BELOW",
          "rvol": float(round(last_t.get("rvol", 1.0), 2)),
          "atr": float(round(last_t.get("atr", 0.5), 2)),
      }
      for e in emas_t:
        if f"ema_{e}" in proc_t.df.columns:
          bundle["trigger"][f"ema_{e}"] = float(
              round(last_t.get(f"ema_{e}", cp_t), 2)
          )

    return bundle