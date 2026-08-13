"""
Core breakout detection engine.
Used by both the backtester and the live scanner.

This module evaluates whether a stock has broken out at a given point in time.
All lookback is strictly backward — no look-ahead bias.
"""

import numpy as np
import pandas as pd
from backend.config import ScreenerConfig
from backend.indicators import (
    sma,
    rsi as calc_rsi,
    bollinger_bands,
    avg_volume,
    avg_turnover,
    n_day_high,
    get_latest_swing_high,
)


def get_resistance_level(
    close_series: pd.Series, idx: int, config: ScreenerConfig
) -> float:
    """
    Calculate the resistance level for a stock at a given index.
    Only uses data BEFORE the current index (no look-ahead).

    Args:
        close_series: Full close price series
        idx: Current bar index (integer position)
        config: Screener configuration

    Returns:
        Resistance level as a float, or NaN if insufficient data.
    """
    mode = config.resistance_mode

    if mode == "52_WEEK_HIGH":
        lookback = 252
        if idx < lookback:
            return np.nan
        # Max of closes from (idx-lookback) to (idx-1), exclusive of current bar
        window = close_series.iloc[max(0, idx - lookback) : idx]
        return window.max()

    elif mode == "N_DAY_HIGH":
        n = config.n_day_lookback
        if idx < n:
            return np.nan
        window = close_series.iloc[max(0, idx - n) : idx]
        return window.max()

    elif mode == "SWING_HIGH":
        resistance = get_latest_swing_high(
            close_series,
            up_to_idx=idx,
            left=config.swing_high_left,
            right=config.swing_high_right,
        )
        return resistance

    else:
        raise ValueError(f"Unknown resistance mode: {mode}")


def evaluate_breakout(
    df: pd.DataFrame, idx: int, config: ScreenerConfig
) -> dict:
    """
    Evaluate whether a breakout occurred at a specific bar index.

    Args:
        df: Stock's OHLCV DataFrame with computed indicators.
            Expected columns: Close, Volume, SMA_200, RSI, Avg_Volume,
            Avg_Turnover_Cr, BB_Width
        idx: Integer position index of the bar to evaluate
        config: Screener configuration

    Returns:
        Dict with breakout details, or None if no breakout / insufficient data.
    """
    if idx < 252:  # Need at least 1 year of data for indicators
        return None

    close = df["Close"].iloc[idx]
    volume = df["Volume"].iloc[idx]

    # --- Check minimum price ---
    if close < config.min_price:
        return None

    # --- Get resistance level ---
    resistance = get_resistance_level(df["Close"], idx, config)
    if np.isnan(resistance):
        return None

    # --- Check breakout condition based on scan_type ---
    is_confirmed_breakout = close > resistance
    pct_from_resistance = ((close - resistance) / resistance) * 100

    if config.scan_type == "NEAR_BREAKOUT":
        # Near breakout: Price is below resistance, but within near_breakout_pct (e.g., within 0% to 2% below)
        is_near = (close <= resistance) and (abs(pct_from_resistance) <= config.near_breakout_pct)
        if not is_near:
            return None
        # Relax volume multiplier for near breakout (building volume)
        min_vol_mult = max(1.0, config.volume_multiplier * 0.7)
    else:
        # Confirmed breakout: close > resistance
        if not is_confirmed_breakout:
            return None
        min_vol_mult = config.volume_multiplier

    # --- Volume confirmation ---
    avg_vol = df["Avg_Volume"].iloc[idx] if "Avg_Volume" in df.columns else None
    if avg_vol is None or np.isnan(avg_vol) or avg_vol == 0:
        return None

    volume_ratio = volume / avg_vol
    if volume_ratio < min_vol_mult:
        return None

    # --- Turnover filter ---
    avg_turn_cr = (
        df["Avg_Turnover_Cr"].iloc[idx] if "Avg_Turnover_Cr" in df.columns else None
    )
    if avg_turn_cr is not None and not np.isnan(avg_turn_cr):
        if avg_turn_cr < config.min_turnover_cr:
            return None

    # --- 200 DMA filter ---
    sma_200 = df["SMA_200"].iloc[idx] if "SMA_200" in df.columns else None
    above_200dma = True
    if sma_200 is not None and not np.isnan(sma_200):
        above_200dma = close > sma_200
        if config.require_above_200dma and not above_200dma:
            return None

    # --- RSI filter ---
    rsi_val = df["RSI"].iloc[idx] if "RSI" in df.columns else None
    if rsi_val is not None and not np.isnan(rsi_val):
        if config.rsi_filter_enabled and rsi_val < config.rsi_threshold:
            return None
    else:
        rsi_val = None

    # --- Calculate percentage above/below resistance ---
    pct_above = pct_from_resistance

    # --- Calculate strength score and factor breakdown ---
    bb_width = df["BB_Width"].iloc[idx] if "BB_Width" in df.columns else None
    strength, score_factors = calculate_strength_score(
        volume_ratio=volume_ratio,
        pct_above=max(0.0, pct_above),
        above_200dma=above_200dma,
        bb_width=bb_width,
        bb_width_series=df["BB_Width"] if "BB_Width" in df.columns else None,
        idx=idx,
        rsi_val=rsi_val,
        config=config,
    )

    # --- Calculate Trade Execution Plan ---
    trade_plan = calculate_trade_plan(resistance, close, df, idx, config)

    # --- Construct Comprehensive Selection Factors for Diagnosis Modal ---
    selection_factors = {
        "resistance": {
            "mode": config.resistance_mode.replace("_", " "),
            "level": round(float(resistance), 2),
            "pct_distance": round(float(pct_above), 2),
            "is_near": config.scan_type == "NEAR_BREAKOUT",
            "summary": f"{abs(round(float(pct_above), 2))}% {'above' if pct_above > 0 else 'below'} prior {config.resistance_mode.replace('_', ' ')} (₹{round(float(resistance), 2)})"
        },
        "volume": {
            "ratio": round(float(volume_ratio), 2),
            "multiplier_required": config.volume_multiplier,
            "avg_turnover_cr": round(float(avg_turn_cr), 2) if avg_turn_cr is not None and not np.isnan(avg_turn_cr) else None,
            "min_turnover_required": config.min_turnover_cr,
            "status": "PASS",
            "summary": f"Volume is {round(float(volume_ratio), 1)}× the 20-day average volume (≥{config.volume_multiplier}× required)"
        },
        "trend": {
            "above_200dma": bool(above_200dma),
            "sma_200": round(float(sma_200), 2) if sma_200 is not None and not np.isnan(sma_200) else None,
            "status": "PASS" if above_200dma else "WARNING",
            "summary": "Stock is in a strong long-term uptrend (Close > 200 DMA)" if above_200dma else "Stock is below 200 DMA (counter-trend move)"
        },
        "consolidation": {
            "bb_width": round(float(bb_width), 2) if bb_width is not None and not np.isnan(bb_width) else None,
            "summary": f"Bollinger Band width is {round(float(bb_width), 1)}% (volatility squeeze before momentum)" if bb_width is not None and not np.isnan(bb_width) else "Bollinger Band width data unavailable"
        },
        "rsi": {
            "value": round(float(rsi_val), 1) if rsi_val is not None and not np.isnan(rsi_val) else None,
            "threshold": config.rsi_threshold if config.rsi_filter_enabled else None,
            "status": "PASS" if (not config.rsi_filter_enabled or (rsi_val and rsi_val >= config.rsi_threshold)) else "FAIL",
            "summary": f"RSI(14) is at {round(float(rsi_val), 1)} (strong momentum)" if rsi_val is not None and not np.isnan(rsi_val) else "RSI data unavailable"
        },
        "score_breakdown": score_factors
    }

    return {
        "is_breakout": True,
        "scan_type": "NEAR_BREAKOUT" if config.scan_type == "NEAR_BREAKOUT" else "BROKEN_OUT",
        "resistance_level": round(float(resistance), 2),
        "close_price": round(float(close), 2),
        "pct_above": round(float(pct_above), 2),
        "volume_ratio": round(float(volume_ratio), 2),
        "rsi": round(float(rsi_val), 2) if rsi_val is not None else None,
        "above_200dma": bool(above_200dma),
        "strength_score": int(strength),
        "trade_plan": trade_plan,
        "selection_factors": selection_factors,
    }


def calculate_trade_plan(
    resistance: float,
    close: float,
    df: pd.DataFrame,
    idx: int,
    config: ScreenerConfig,
) -> dict:
    """
    Calculate actionable entry trigger, stop-loss, targets, and position sizing.
    """
    import math

    entry_trigger = round(float(resistance) * (1.0 + config.entry_buffer_pct / 100.0), 2)

    # Stop-loss based on 20-day low or fallback %
    lookback_20d = df["Low"].iloc[max(0, idx - 20) : idx] if "Low" in df.columns else None
    min_20d_low = float(lookback_20d.min()) if lookback_20d is not None and not lookback_20d.empty and not pd.isna(lookback_20d.min()) else None

    fallback_sl = entry_trigger * (1.0 - config.default_stop_loss_pct / 100.0)

    if min_20d_low and min_20d_low < entry_trigger and (entry_trigger - min_20d_low) / entry_trigger <= 0.08:
        stop_loss = round(min_20d_low, 2)
    else:
        stop_loss = round(fallback_sl, 2)

    risk_per_share = round(entry_trigger - stop_loss, 2)
    if risk_per_share <= 0:
        risk_per_share = round(entry_trigger * 0.03, 2)
        stop_loss = round(entry_trigger - risk_per_share, 2)

    risk_pct = round((risk_per_share / entry_trigger) * 100.0, 2)

    target_1 = round(entry_trigger + (risk_per_share * config.risk_reward_ratio), 2)
    target_1_pct = round(((target_1 - entry_trigger) / entry_trigger) * 100.0, 2)

    target_2 = round(entry_trigger + (risk_per_share * 3.0), 2)
    target_2_pct = round(((target_2 - entry_trigger) / entry_trigger) * 100.0, 2)

    risk_budget = config.risk_per_trade_inr
    suggested_shares = math.floor(risk_budget / risk_per_share) if risk_per_share > 0 else 0
    position_capital = round(suggested_shares * entry_trigger, 2)

    return {
        "entry_trigger": entry_trigger,
        "stop_loss": stop_loss,
        "risk_per_share": risk_per_share,
        "risk_pct": risk_pct,
        "target_1": target_1,
        "target_1_pct": target_1_pct,
        "target_2": target_2,
        "target_2_pct": target_2_pct,
        "suggested_shares": suggested_shares,
        "risk_budget_inr": risk_budget,
        "position_capital": position_capital,
    }


def calculate_strength_score(
    volume_ratio: float,
    pct_above: float,
    above_200dma: bool,
    bb_width: float,
    bb_width_series: pd.Series,
    idx: int,
    rsi_val: float,
    config: ScreenerConfig,
) -> tuple:
    """
    Calculate a 1-100 strength score and return factor breakdown.
    """
    # Volume component: normalize to 0-1, cap at 5x
    vol_score = min(volume_ratio / 5.0, 1.0)

    # Price gap component: normalize to 0-1, cap at 5%
    gap_score = min(pct_above / 5.0, 1.0) if pct_above > 0 else 0.8  # Near breakout gets 0.8 for gap proximity

    # Trend component: binary
    trend_score = 1.0 if above_200dma else 0.3

    # Consolidation component: based on BB width percentile
    consol_score = 0.5  # default if no data
    if (
        bb_width is not None
        and bb_width_series is not None
        and not np.isnan(bb_width)
    ):
        lookback = min(idx, 252)
        if lookback > 20:
            recent_bb = bb_width_series.iloc[max(0, idx - lookback) : idx + 1]
            recent_bb = recent_bb.dropna()
            if len(recent_bb) > 10:
                percentile = (recent_bb < bb_width).sum() / len(recent_bb)
                consol_score = 1.0 - percentile  # Tighter (lower width) = higher score

    # RSI component: normalize to 0-1, cap at 80
    rsi_score = 0.5  # default
    if rsi_val is not None and not np.isnan(rsi_val):
        rsi_score = min(rsi_val / 80.0, 1.0)

    # Weighted sum
    raw_score = (
        config.weight_volume * vol_score
        + config.weight_price_gap * gap_score
        + config.weight_trend * trend_score
        + config.weight_consolidation * consol_score
        + config.weight_rsi * rsi_score
    )

    final_score = max(1, min(100, int(round(raw_score * 100))))

    factors = {
        "volume_points": round(vol_score * config.weight_volume * 100, 1),
        "volume_max": int(config.weight_volume * 100),
        "gap_points": round(gap_score * config.weight_price_gap * 100, 1),
        "gap_max": int(config.weight_price_gap * 100),
        "trend_points": round(trend_score * config.weight_trend * 100, 1),
        "trend_max": int(config.weight_trend * 100),
        "consol_points": round(consol_score * config.weight_consolidation * 100, 1),
        "consol_max": int(config.weight_consolidation * 100),
        "rsi_points": round(rsi_score * config.weight_rsi * 100, 1),
        "rsi_max": int(config.weight_rsi * 100),
        "total_score": final_score
    }

    return final_score, factors
