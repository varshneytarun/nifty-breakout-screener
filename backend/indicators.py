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


def compute_all_indicators(df: pd.DataFrame, config=None) -> pd.DataFrame:
    """
    Compute all technical indicators for a stock's OHLCV DataFrame.
    Adds indicator columns in-place and returns the DataFrame.

    Expected input columns: Open, High, Low, Close, Volume
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

    # RSI
    df["RSI"] = rsi(close, 14)

    # Bollinger Bands
    bb = bollinger_bands(close, 20, 2.0)
    df["BB_Upper"] = bb["upper"]
    df["BB_Lower"] = bb["lower"]
    df["BB_Width"] = bb["bandwidth"]

    # Volume
    df["Avg_Volume"] = avg_volume(volume, config.volume_lookback)
    df["Volume_Ratio"] = volume / df["Avg_Volume"]

    # Turnover (in ₹ Crores)
    df["Avg_Turnover_Cr"] = avg_turnover(close, volume, 20) / 1e7

    # Resistance levels
    df["High_52W"] = n_day_high(close, 252)
    df["High_N"] = n_day_high(close, config.n_day_lookback)

    return df
