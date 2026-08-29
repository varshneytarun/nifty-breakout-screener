"""
Pure-function technical indicator calculations using pandas.
All functions take pandas Series/DataFrames and return pandas Series/values.
No side effects, no database access.
"""

import pandas as pd
import numpy as np


def sma(series: pd.Series, period: int) -> pd.Series:
    """Simple Moving Average."""
    return series.rolling(window=period, min_periods=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average."""
    return series.ewm(span=period, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """
    Relative Strength Index using Wilder's smoothing method.
    Returns values between 0 and 100.
    """
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)

    # Wilder's smoothing (exponential moving average with alpha = 1/period)
    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss
    rsi_values = 100.0 - (100.0 / (1.0 + rs))

    return rsi_values


def bollinger_bands(
    series: pd.Series, period: int = 20, num_std: float = 2.0
) -> dict:
    """
    Bollinger Bands.
    Returns dict with 'upper', 'middle', 'lower', 'bandwidth' Series.
    """
    middle = sma(series, period)
    std = series.rolling(window=period, min_periods=period).std()

    upper = middle + (num_std * std)
    lower = middle - (num_std * std)

    # Bandwidth = (Upper - Lower) / Middle, as percentage
    bandwidth = ((upper - lower) / middle) * 100

    return {
        "upper": upper,
        "middle": middle,
        "lower": lower,
        "bandwidth": bandwidth,
    }


def avg_volume(volume: pd.Series, period: int = 20) -> pd.Series:
    """Average volume over a rolling window."""
    return volume.rolling(window=period, min_periods=period).mean()


def avg_turnover(close: pd.Series, volume: pd.Series, period: int = 20) -> pd.Series:
    """
    Average daily turnover (Close × Volume) over a rolling window.
    Returns values in raw ₹ (divide by 1e7 for ₹ Crores).
    """
    daily_turnover = close * volume
    return daily_turnover.rolling(window=period, min_periods=period).mean()


def n_day_high(series: pd.Series, n: int) -> pd.Series:
    """
    Rolling N-day high (maximum close over the last N days).
    The current day is EXCLUDED to represent prior resistance.
    """
    return series.shift(1).rolling(window=n, min_periods=n).max()


def n_day_low(series: pd.Series, n: int) -> pd.Series:
    """Rolling N-day low."""
    return series.shift(1).rolling(window=n, min_periods=n).min()


def find_swing_highs(series: pd.Series, left: int = 5, right: int = 5) -> pd.Series:
    """
    Detect swing highs (local maxima / pivot highs).

    A swing high at index i means:
    - series[i] is greater than all values in [i-left, i-1]
    - series[i] is greater than all values in [i+1, i+right]

    Returns a boolean Series (True at swing high positions).
    """
    swing_highs = pd.Series(False, index=series.index)

    for i in range(left, len(series) - right):
        current = series.iloc[i]
        left_window = series.iloc[i - left : i]
        right_window = series.iloc[i + 1 : i + right + 1]

        if (current > left_window).all() and (current > right_window).all():
            swing_highs.iloc[i] = True

    return swing_highs


def get_latest_swing_high(series: pd.Series, up_to_idx: int, left: int = 5, right: int = 5) -> float:
    """
    Get the most recent swing high value before a given index.
    Used for resistance level detection.

    Args:
        series: Price series (typically Close)
        up_to_idx: Only consider swing highs before this index (prevents look-ahead)
        left: Bars to the left for pivot detection
        right: Bars to the right for pivot detection

    Returns:
        The price level of the most recent swing high, or NaN if none found.
    """
    # We need at least left+right+1 bars, and swing highs can only be detected
    # up to (up_to_idx - right) because we need 'right' bars after the pivot
    max_pivot_idx = up_to_idx - right

    if max_pivot_idx < left:
        return np.nan

    # Search backwards from the most recent valid pivot position
    for i in range(max_pivot_idx, left - 1, -1):
        current = series.iloc[i]
        left_window = series.iloc[i - left : i]
        right_window = series.iloc[i + 1 : i + right + 1]

        if (current > left_window).all() and (current > right_window).all():
            return current

    return np.nan


def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Average True Range (ATR) calculation.
    """
    high = df["High"]
    low = df["Low"]
    close = df["Close"]
    prev_close = close.shift(1)

    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()

    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    # Wilder's smoothing for ATR
    atr = tr.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    return atr


def calculate_vcp(df: pd.DataFrame, atr_period: int = 14, lookback: int = 50) -> dict:
    """
    Volatility Contraction Pattern (VCP / Minervini style) detector.
    Measures progressive ATR compression and tightening pullback depths.
    """
    if len(df) < lookback + atr_period:
        return {
            "atr_ratio": 1.0,
            "is_vcp": False,
            "vcp_score": 0,
            "compression_pct": 0.0,
        }

    atr_series = calculate_atr(df, atr_period)
    atr_avg = atr_series.rolling(window=lookback, min_periods=20).mean()
    atr_ratio_series = atr_series / (atr_avg + 1e-8)

    latest_atr_ratio = float(atr_ratio_series.iloc[-1]) if not atr_ratio_series.empty else 1.0

    # Measure price range contraction over 3 consecutive 15-day blocks
    close = df["Close"]
    range_last15 = (close.iloc[-15:].max() - close.iloc[-15:].min()) / close.iloc[-15:].mean() if len(close) >= 15 else 1.0
    range_prev15 = (close.iloc[-30:-15].max() - close.iloc[-30:-15].min()) / close.iloc[-30:-15].mean() if len(close) >= 30 else 1.0
    range_prev30 = (close.iloc[-45:-30].max() - close.iloc[-45:-30].min()) / close.iloc[-45:-30].mean() if len(close) >= 45 else 1.0

    is_contracting = (range_last15 < range_prev15) and (latest_atr_ratio < 0.85)

    # VCP score from 0 to 100
    vcp_score = 0
    if latest_atr_ratio < 0.70:
        vcp_score += 45
    elif latest_atr_ratio < 0.85:
        vcp_score += 30
    elif latest_atr_ratio < 1.0:
        vcp_score += 15

    if is_contracting:
        vcp_score += 35

    if range_last15 < 0.06:  # Less than 6% price range in last 15 days = ultra tight base
        vcp_score += 20

    compression_pct = round((1.0 - latest_atr_ratio) * 100.0, 1)

    return {
        "atr_series": atr_series,
        "atr_ratio": round(latest_atr_ratio, 3),
        "is_vcp": bool(vcp_score >= 60),
        "vcp_score": int(min(100, vcp_score)),
        "compression_pct": compression_pct,
    }


def calculate_mansfield_rs(
    stock_close: pd.Series, benchmark_close: pd.Series, lookback: int = 50
) -> pd.Series:
    """
    Mansfield Relative Strength vs Nifty 50 Benchmark.
    Positive values (> 0) indicate outperformance against the index.
    Rising RS line indicates institutional accumulation.
    """
    # Align dates
    combined = pd.DataFrame({"stock": stock_close, "benchmark": benchmark_close}).dropna()
    if len(combined) < lookback:
        return pd.Series(0.0, index=stock_close.index)

    rel_perf = combined["stock"] / combined["benchmark"]
    base_sma = rel_perf.rolling(window=lookback, min_periods=lookback).mean()
    mansfield_rs = ((rel_perf / base_sma) - 1.0) * 100.0

    # Reindex back to original series
    return mansfield_rs.reindex(stock_close.index, fill_value=0.0)


def calculate_market_regime(benchmark_df: pd.DataFrame) -> dict:
    """
    Classify Nifty 50 market regime for breakout trading.
    - BULL_TREND: Close > 50 EMA > 200 SMA (Ideal environment for breakouts)
    - CHOPPY_NEUTRAL: Close around 50 EMA (Higher failure rate, trade selectively)
    - BEAR_CORRECTION: Close < 200 SMA (Dangerous for breakouts, high false breakout risk)
    """
    if benchmark_df.empty or len(benchmark_df) < 50:
        return {
            "regime": "NEUTRAL",
            "badge": "🟡 Market Neutral",
            "advice": "Trade with standard position sizing.",
            "nifty_close": 0.0,
            "above_50ema": False,
            "above_200sma": False,
            "score_modifier": 1.0,
        }

    close = benchmark_df["Close"]
    latest_close = float(close.iloc[-1])

    ema_20 = float(ema(close, 20).iloc[-1])
    ema_50 = float(ema(close, 50).iloc[-1])
    sma_200 = float(sma(close, 200).iloc[-1]) if len(close) >= 200 else latest_close * 0.95

    dist_50 = ((latest_close - ema_50) / ema_50) * 100.0

    if latest_close > ema_50 and ema_50 > sma_200:
        regime = "BULL_TREND"
        badge = "🟢 Bull Market (Nifty Uptrend)"
        advice = "Favorable tailwind. Breakouts have high probability of follow-through."
        modifier = 1.15
    elif latest_close < sma_200:
        regime = "BEAR_CORRECTION"
        badge = "🔴 Market Correction (Nifty < 200 DMA)"
        advice = "High failure risk. Take only 5-star setups and reduce position size by 50%."
        modifier = 0.70
    else:
        regime = "CHOPPY_NEUTRAL"
        badge = "🟡 Rangebound / Choppy"
        advice = "Selective market. Prioritize stocks with top Relative Strength and tight VCP."
        modifier = 0.90

    return {
        "regime": regime,
        "badge": badge,
        "advice": advice,
        "nifty_close": round(latest_close, 2),
        "nifty_50ema": round(ema_50, 2),
        "nifty_200sma": round(sma_200, 2),
        "dist_50_pct": round(dist_50, 2),
        "above_50ema": bool(latest_close > ema_50),
        "above_200sma": bool(latest_close > sma_200),
        "score_modifier": modifier,
    }


def compute_all_indicators(df: pd.DataFrame, config=None, benchmark_df=None) -> pd.DataFrame:
    """
    Compute all technical indicators for a stock's OHLCV DataFrame.
    Adds indicator columns in-place and returns the DataFrame.
    """
    from backend.config import ScreenerConfig

    if config is None:
        config = ScreenerConfig()

    close = df["Close"]
    volume = df["Volume"]

    # Moving averages
    df["SMA_200"] = sma(close, 200)
    df["SMA_50"] = sma(close, 50)
    df["SMA_20"] = sma(close, 20)
    df["EMA_20"] = ema(close, 20)

    # RSI
    df["RSI"] = rsi(close, 14)

    # Bollinger Bands
    bb = bollinger_bands(close, 20, 2.0)
    df["BB_Upper"] = bb["upper"]
    df["BB_Lower"] = bb["lower"]
    df["BB_Width"] = bb["bandwidth"]

    # ATR & Volatility
    df["ATR"] = calculate_atr(df, 14)
    atr_avg = df["ATR"].rolling(window=50, min_periods=20).mean()
    df["ATR_Ratio"] = df["ATR"] / (atr_avg + 1e-8)

    # Volume
    df["Avg_Volume"] = avg_volume(volume, config.volume_lookback)
    df["Volume_Ratio"] = volume / df["Avg_Volume"]

    # Turnover (in ₹ Crores)
    df["Avg_Turnover_Cr"] = avg_turnover(close, volume, 20) / 1e7

    # Resistance levels
    df["High_52W"] = n_day_high(close, 252)
    df["High_N"] = n_day_high(close, config.n_day_lookback)

    # Relative Strength vs Benchmark
    if benchmark_df is not None and not benchmark_df.empty:
        df["Mansfield_RS"] = calculate_mansfield_rs(df["Close"], benchmark_df["Close"], 50)
    else:
        df["Mansfield_RS"] = 0.0

    return df

