"""
Backtesting engine.
Runs the breakout screener across historical data to validate signal quality.

For each trading day in the backtest window, checks every stock for breakout signals,
then measures forward returns to see how the signals performed.
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import logging

from backend.config import ScreenerConfig
from backend.database import (
    get_all_symbols,
    get_ohlcv,
    save_backtest_signals,
    clear_backtest_signals,
    get_backtest_signals,
    get_backtest_signal_count,
    get_stock_info,
)
from backend.data_fetcher import get_stock_data_with_indicators
from backend.screener import evaluate_breakout

logger = logging.getLogger(__name__)


def run_backtest(
    config: ScreenerConfig = None,
    symbols: list = None,
    progress_callback=None,
) -> dict:
    """
    Run the backtester over the last N years of data.

    For each trading day in the backtest window:
    1. Check each stock for a breakout signal (using only data available up to that day)
    2. Record the signal
    3. Compute forward returns at 5, 10, 20, 30 days

    Args:
        config: Screener configuration
        symbols: List of symbols to backtest. If None, uses all Nifty 500.
        progress_callback: Optional callback(current, total, message)

    Returns:
        Dict with backtest summary statistics.
    """
    if config is None:
        config = ScreenerConfig()

    if symbols is None:
        symbols = get_all_symbols()

    # Clear previous backtest results
    clear_backtest_signals()

    total_symbols = len(symbols)
    all_signals = []

    for sym_idx, symbol in enumerate(symbols):
        try:
            # Get full OHLCV data with indicators
            df = get_stock_data_with_indicators(symbol, config)

            if df.empty or len(df) < 300:
                # Need at least ~300 bars (252 for 52-week lookback + some buffer)
                continue

            # Determine the backtest window
            # We need 252+ bars of lookback, so start from bar 252
            total_bars = len(df)

            # Backtest window: last ~252 trading days (1 year)
            backtest_start_idx = max(252, total_bars - 252)

            # We need forward returns, so stop 30 bars before end
            backtest_end_idx = total_bars - max(config.forward_return_days) - 1

            if backtest_start_idx >= backtest_end_idx:
                continue

            for idx in range(backtest_start_idx, backtest_end_idx):
                result = evaluate_breakout(df, idx, config)

                if result and result["is_breakout"]:
                    signal_date = df.index[idx].strftime("%Y-%m-%d")

                    # Compute forward returns
                    current_close = df["Close"].iloc[idx]
                    forward_returns = {}

                    for fwd_days in config.forward_return_days:
                        fwd_idx = idx + fwd_days
                        if fwd_idx < total_bars:
                            fwd_close = df["Close"].iloc[fwd_idx]
                            fwd_return = ((fwd_close - current_close) / current_close) * 100
                            forward_returns[f"return_{fwd_days}d"] = round(fwd_return, 2)
                        else:
                            forward_returns[f"return_{fwd_days}d"] = None

                    signal = {
                        "signal_date": signal_date,
                        "symbol": symbol,
                        "resistance_mode": config.resistance_mode,
                        "resistance_level": result["resistance_level"],
                        "close_price": result["close_price"],
                        "pct_above": result["pct_above"],
                        "volume_ratio": result["volume_ratio"],
                        "rsi": result["rsi"],
                        "above_200dma": 1 if result["above_200dma"] else 0,
                        "strength_score": result["strength_score"],
                        **forward_returns,
                    }

                    all_signals.append(signal)

        except Exception as e:
            logger.error(f"Backtest error for {symbol}: {e}")

        if progress_callback and (sym_idx + 1) % 10 == 0:
            progress_callback(
                sym_idx + 1,
                total_symbols,
                f"Backtested {sym_idx + 1}/{total_symbols} stocks, {len(all_signals)} signals found..."
            )

    # Save all signals to database
    if all_signals:
        # Batch insert for performance
        batch_size = 500
        for i in range(0, len(all_signals), batch_size):
            batch = all_signals[i : i + batch_size]
            save_backtest_signals(batch)

    if progress_callback:
        progress_callback(total_symbols, total_symbols, f"Backtest complete! {len(all_signals)} signals found.")

    # Compute and return statistics
    stats = compute_backtest_stats(all_signals, config)
    return stats


def compute_backtest_stats(signals: list = None, config: ScreenerConfig = None) -> dict:
    """
    Compute aggregate statistics from backtest signals.

    Returns a comprehensive stats dict for the frontend dashboard.
    """
    if config is None:
        config = ScreenerConfig()

    # If signals not provided, load from database
    if signals is None:
        signals = get_backtest_signals(limit=100000)

    if not signals:
        return {
            "total_signals": 0,
            "message": "No breakout signals found. Try relaxing filters.",
        }

    df = pd.DataFrame(signals)
    total = len(df)

    stats = {
        "total_signals": total,
        "date_range": {
            "start": df["signal_date"].min(),
            "end": df["signal_date"].max(),
        },
        "avg_strength_score": round(df["strength_score"].mean(), 1),
        "avg_volume_ratio": round(df["volume_ratio"].mean(), 2),
        "avg_pct_above": round(df["pct_above"].mean(), 2),
    }

    # --- Forward return stats for each period ---
    for days in config.forward_return_days:
        col = f"return_{days}d"
        if col in df.columns:
            valid = df[col].dropna()
            if len(valid) > 0:
                winners = valid[valid > 0]
                losers = valid[valid <= 0]

                stats[f"stats_{days}d"] = {
                    "total_signals": len(valid),
                    "win_rate": round(len(winners) / len(valid) * 100, 1),
                    "avg_return": round(valid.mean(), 2),
                    "median_return": round(valid.median(), 2),
                    "avg_winner": round(winners.mean(), 2) if len(winners) > 0 else 0,
                    "avg_loser": round(losers.mean(), 2) if len(losers) > 0 else 0,
                    "best_return": round(valid.max(), 2),
                    "worst_return": round(valid.min(), 2),
                    "std_dev": round(valid.std(), 2),
                }

    # --- Score bucket analysis ---
    buckets = [
        (80, 100, "80-100"),
        (60, 79, "60-79"),
        (40, 59, "40-59"),
        (20, 39, "20-39"),
        (1, 19, "1-19"),
    ]

    score_analysis = []
    for low, high, label in buckets:
        bucket_df = df[(df["strength_score"] >= low) & (df["strength_score"] <= high)]
        if len(bucket_df) == 0:
            continue

        bucket_stats = {"bucket": label, "count": len(bucket_df)}

        for days in config.forward_return_days:
            col = f"return_{days}d"
            if col in bucket_df.columns:
                valid = bucket_df[col].dropna()
                if len(valid) > 0:
                    winners = valid[valid > 0]
                    bucket_stats[f"win_rate_{days}d"] = round(
                        len(winners) / len(valid) * 100, 1
                    )
                    bucket_stats[f"avg_return_{days}d"] = round(valid.mean(), 2)

        score_analysis.append(bucket_stats)

    stats["score_buckets"] = score_analysis

    # --- Monthly distribution ---
    if "signal_date" in df.columns:
        df["month"] = pd.to_datetime(df["signal_date"]).dt.to_period("M").astype(str)
        monthly = (
            df.groupby("month")
            .agg(
                count=("symbol", "count"),
                avg_score=("strength_score", "mean"),
            )
            .reset_index()
        )
        monthly["avg_score"] = monthly["avg_score"].round(1)
        stats["monthly_distribution"] = monthly.to_dict("records")

    # --- Industry distribution ---
    if "industry" in df.columns:
        industry = (
            df.groupby("industry")
            .agg(
                count=("symbol", "count"),
                avg_score=("strength_score", "mean"),
            )
            .reset_index()
            .sort_values("count", ascending=False)
            .head(15)
        )
        industry["avg_score"] = industry["avg_score"].round(1)
        stats["industry_distribution"] = industry.to_dict("records")

    # --- Top signals ---
    top_signals = (
        df.nlargest(10, "strength_score")[
            ["signal_date", "symbol", "strength_score", "pct_above", "volume_ratio",
             "return_5d", "return_10d", "return_20d", "return_30d"]
        ].to_dict("records")
    )
    stats["top_signals"] = top_signals

    return stats
