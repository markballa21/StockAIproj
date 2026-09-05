# src/ui_helpers.py
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from typing import Dict, Any, Optional


def color_action(val: str) -> str:
    """מנגנון צביעת פעולות עבור טבלאות AI."""
    if val == "BUY":
        return "background-color: #1b5e20; color: white; font-weight: bold;"
    elif val == "SELL":
        return "background-color: #b71c1c; color: white; font-weight: bold;"
    return "color: #9e9e9e;"


def render_candlestick_chart(
        df: pd.DataFrame,
        indicators_config: Optional[Dict[str, Any]] = None,
        height: int = 550,
) -> go.Figure:
    """יצירת גרף נרות Plotly סטנדרטי ואינטראקטיבי."""
    indicators_config = indicators_config or {}

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.75, 0.25],
    )

    # 1. נרות OHLC
    fig.add_trace(
        go.Candlestick(
            x=df["timestamp"],
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            name="OHLC",
            increasing_line_color="#26a69a",
            decreasing_line_color="#ef5350",
        ),
        row=1, col=1
    )

    # 2. אינדיקטורים דינמיים
    if indicators_config.get("show_vwap", True) and "vwap" in df.columns:
        fig.add_trace(
            go.Scatter(
                x=df["timestamp"],
                y=df["vwap"],
                name="VWAP",
                line=dict(color="#ffa726", width=1.5),
            ),
            row=1, col=1
        )

    if indicators_config.get("show_sma", False):
        sma_val = indicators_config.get("sma_val", 150)
        sma_col = f"sma_{sma_val}"
        if sma_col in df.columns:
            fig.add_trace(
                go.Scatter(
                    x=df["timestamp"],
                    y=df[sma_col],
                    name=f"SMA {sma_val}",
                    line=dict(color="#FFD700", width=1.8, dash="dot"),
                ),
                row=1, col=1
            )

    if indicators_config.get("show_ema", False):
        if "ema_20" in df.columns:
            fig.add_trace(
                go.Scatter(x=df["timestamp"], y=df["ema_20"], name="EMA 20", line=dict(color="#29b6f6", width=1.2)),
                row=1, col=1)
        if "ema_50" in df.columns:
            fig.add_trace(
                go.Scatter(x=df["timestamp"], y=df["ema_50"], name="EMA 50", line=dict(color="#ab47bc", width=1.2)),
                row=1, col=1)

    # 3. Pivot Points
    if indicators_config.get("show_pivots", False) and "pivot_high_price" in df.columns:
        p_highs = df[df.get("is_pivot_high", False)]
        p_lows = df[df.get("is_pivot_low", False)]

        if not p_highs.empty:
            fig.add_trace(
                go.Scatter(
                    x=p_highs["timestamp"],
                    y=p_highs["pivot_high_price"],
                    mode="markers",
                    name="Pivot High",
                    marker=dict(symbol="triangle-down", size=9, color="#FF1744"),
                ),
                row=1, col=1
            )
        if not p_lows.empty:
            fig.add_trace(
                go.Scatter(
                    x=p_lows["timestamp"],
                    y=p_lows["pivot_low_price"],
                    mode="markers",
                    name="Pivot Low",
                    marker=dict(symbol="triangle-up", size=9, color="#00E676"),
                ),
                row=1, col=1
            )

    # 4. קווי Support / Resistance
    if indicators_config.get("show_zones", False):
        if "nearest_resistance" in df.columns and pd.notna(df["nearest_resistance"].iloc[-1]):
            res_val = df["nearest_resistance"].iloc[-1]
            fig.add_hline(y=res_val, line_dash="dash", line_color="#FF5252", line_width=1.2,
                          annotation_text=f"Res: {res_val:.2f}", row=1, col=1)
        if "nearest_support" in df.columns and pd.notna(df["nearest_support"].iloc[-1]):
            sup_val = df["nearest_support"].iloc[-1]
            fig.add_hline(y=sup_val, line_dash="dash", line_color="#69F0AE", line_width=1.2,
                          annotation_text=f"Sup: {sup_val:.2f}", row=1, col=1)

    # 5. Volume
    colors = ["#26a69a" if c >= o else "#ef5350" for o, c in zip(df["open"], df["close"])]
    fig.add_trace(
        go.Bar(
            x=df["timestamp"],
            y=df["volume"],
            name="Volume",
            marker_color=colors,
            opacity=0.7,
        ),
        row=2, col=1
    )

    # עיצוב כללי
    fig.update_layout(
        template="plotly_dark",
        xaxis_rangeslider_visible=False,
        height=height,
        margin=dict(l=10, r=10, t=25, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified",
    )
    fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])
    fig.update_yaxes(title_text="Price ($)", row=1, col=1)
    fig.update_yaxes(title_text="Vol", row=2, col=1)

    return fig