"""
FastAPI application — serves the REST API and static frontend.
"""

import asyncio
import json
import logging
import math
from datetime import datetime
from typing import Optional
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from fastapi import FastAPI, Query, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import os


class NumpyEncoder(json.JSONEncoder):
    """JSON encoder that handles numpy types."""
    def default(self, obj):
        if isinstance(obj, np.bool_):
            return bool(obj)
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            if np.isnan(obj):
                return None
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)


def sanitize_for_json(obj):
    """Recursively convert numpy types to native Python types."""
    if isinstance(obj, dict):
        return {k: sanitize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_for_json(v) for v in obj]
    elif isinstance(obj, np.bool_):
        return bool(obj)
    elif isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.floating):
        return None if np.isnan(obj) else float(obj)
    elif isinstance(obj, float) and math.isnan(obj):
        return None
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj

from backend.config import ScreenerConfig, BASE_DIR
from backend.database import (
    init_db,
    get_data_status,
    get_all_symbols,
    get_backtest_signals,
    get_backtest_signal_count,
    get_stock_info,
    save_scan_results,
)
from backend.data_fetcher import (
    initialize_stock_universe,
    sync_all_stocks,
    get_stock_data_with_indicators,
)
from backend.backtester import run_backtest, compute_backtest_stats
from backend.screener import evaluate_breakout

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Breakout Screener", version="1.0.0")

# CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Thread pool for running blocking yfinance/pandas operations
executor = ThreadPoolExecutor(max_workers=4)

# Track running operations
_running_ops = {}


@app.on_event("startup")
async def startup():
    """Initialize database and stock universe on startup."""
    init_db()
    symbols = get_all_symbols()
    if not symbols:
        initialize_stock_universe()
        logger.info("Stock universe initialized")


def _parse_config(
    resistance_mode: str = None,
    n_day_lookback: int = None,
    volume_multiplier: float = None,
    volume_lookback: int = None,
    scan_type: str = None,
    near_breakout_pct: float = None,
    risk_per_trade_inr: float = None,
    risk_reward_ratio: float = None,
    min_price: float = None,
    min_turnover_cr: float = None,
    require_above_200dma: bool = None,
    rsi_filter_enabled: bool = None,
    rsi_threshold: float = None,
) -> ScreenerConfig:
    """Build a ScreenerConfig from optional query parameters."""
    config = ScreenerConfig()
    if resistance_mode is not None:
        config.resistance_mode = resistance_mode
    if n_day_lookback is not None:
        config.n_day_lookback = n_day_lookback
    if volume_multiplier is not None:
        config.volume_multiplier = volume_multiplier
    if volume_lookback is not None:
        config.volume_lookback = volume_lookback
    if scan_type is not None:
        config.scan_type = scan_type
    if near_breakout_pct is not None:
        config.near_breakout_pct = near_breakout_pct
    if risk_per_trade_inr is not None:
        config.risk_per_trade_inr = risk_per_trade_inr
    if risk_reward_ratio is not None:
        config.risk_reward_ratio = risk_reward_ratio
    if min_price is not None:
        config.min_price = min_price
    if min_turnover_cr is not None:
        config.min_turnover_cr = min_turnover_cr
    if require_above_200dma is not None:
        config.require_above_200dma = require_above_200dma
    if rsi_filter_enabled is not None:
        config.rsi_filter_enabled = rsi_filter_enabled
    if rsi_threshold is not None:
        config.rsi_threshold = rsi_threshold
    return config


# ─── Config ─────────────────────────────────────────────────────────────────

@app.get("/api/config")
async def get_config():
    """Get default screener configuration."""
    return ScreenerConfig().to_dict()


# ─── Data Sync ──────────────────────────────────────────────────────────────

@app.get("/api/data/status")
async def data_status():
    """Check data freshness."""
    return get_data_status()


@app.post("/api/data/sync")
async def sync_data():
    """
    Trigger data sync for all stocks.
    Returns a streaming response with progress updates.
    """
    async def generate():
        progress_state = {"current": 0, "total": 0, "message": "Starting sync..."}

        def progress_callback(current, total, message):
            progress_state["current"] = current
            progress_state["total"] = total
            progress_state["message"] = message

        loop = asyncio.get_event_loop()

        # Send initial message
        yield f"data: {json.dumps(progress_state)}\n\n"

        # Run sync in thread pool
        future = loop.run_in_executor(
            executor,
            lambda: sync_all_stocks(progress_callback=progress_callback)
        )

        # Poll progress while sync runs
        while not future.done():
            await asyncio.sleep(1)
            yield f"data: {json.dumps(progress_state)}\n\n"

        result = future.result()
        final = {
            "current": progress_state["total"],
            "total": progress_state["total"],
            "message": "Sync complete!",
            "result": result,
            "done": True,
        }
        yield f"data: {json.dumps(final)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


# ─── Backtest ───────────────────────────────────────────────────────────────

@app.post("/api/backtest/run")
async def run_backtest_endpoint(
    resistance_mode: str = Query(default=None),
    n_day_lookback: int = Query(default=None),
    volume_multiplier: float = Query(default=None),
    volume_lookback: int = Query(default=None),
    min_price: float = Query(default=None),
    min_turnover_cr: float = Query(default=None),
    require_above_200dma: bool = Query(default=None),
    rsi_filter_enabled: bool = Query(default=None),
    rsi_threshold: float = Query(default=None),
):
    """
    Run the backtester with given configuration.
    Returns streaming progress updates.
    """
    config = _parse_config(
        resistance_mode=resistance_mode,
        n_day_lookback=n_day_lookback,
        volume_multiplier=volume_multiplier,
        volume_lookback=volume_lookback,
        min_price=min_price,
        min_turnover_cr=min_turnover_cr,
        require_above_200dma=require_above_200dma,
        rsi_filter_enabled=rsi_filter_enabled,
        rsi_threshold=rsi_threshold,
    )

    async def generate():
        progress_state = {"current": 0, "total": 0, "message": "Starting backtest..."}

        def progress_callback(current, total, message):
            progress_state["current"] = current
            progress_state["total"] = total
            progress_state["message"] = message

        loop = asyncio.get_event_loop()

        yield f"data: {json.dumps(progress_state)}\n\n"

        future = loop.run_in_executor(
            executor,
            lambda: run_backtest(config=config, progress_callback=progress_callback)
        )

        while not future.done():
            await asyncio.sleep(1)
            yield f"data: {json.dumps(progress_state)}\n\n"

        stats = future.result()
        final = {
            "current": progress_state["total"],
            "total": progress_state["total"],
            "message": "Backtest complete!",
            "done": True,
            "stats": stats,
        }
        yield f"data: {json.dumps(final)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/api/backtest/results")
async def backtest_results():
    """Get aggregated backtest statistics."""
    stats = compute_backtest_stats()
    return sanitize_for_json(stats)


@app.get("/api/backtest/signals")
async def backtest_signals(
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    sort_by: str = Query(default="strength_score"),
    sort_dir: str = Query(default="DESC"),
    symbol: str = Query(default=None),
    min_score: int = Query(default=None),
):
    """Get individual backtest signals with pagination and filtering."""
    signals = get_backtest_signals(
        limit=limit,
        offset=offset,
        sort_by=sort_by,
        sort_dir=sort_dir,
        symbol=symbol,
        min_score=min_score,
    )
    total = get_backtest_signal_count()
    return {"signals": signals, "total": total}


# ─── Live Scanner ───────────────────────────────────────────────────────────

@app.get("/api/scan")
async def live_scan(
    resistance_mode: str = Query(default=None),
    n_day_lookback: int = Query(default=None),
    volume_multiplier: float = Query(default=None),
    volume_lookback: int = Query(default=None),
    scan_type: str = Query(default=None),
    near_breakout_pct: float = Query(default=None),
    risk_per_trade_inr: float = Query(default=None),
    risk_reward_ratio: float = Query(default=None),
    min_price: float = Query(default=None),
    min_turnover_cr: float = Query(default=None),
    require_above_200dma: bool = Query(default=None),
    rsi_filter_enabled: bool = Query(default=None),
    rsi_threshold: float = Query(default=None),
):
    """
    Run the live screener — detect today's breakouts or near-breakout setups.
    Returns a list of breakout stocks sorted by strength score with trade plans.
    """
    config = _parse_config(
        resistance_mode=resistance_mode,
        n_day_lookback=n_day_lookback,
        volume_multiplier=volume_multiplier,
        volume_lookback=volume_lookback,
        scan_type=scan_type,
        near_breakout_pct=near_breakout_pct,
        risk_per_trade_inr=risk_per_trade_inr,
        risk_reward_ratio=risk_reward_ratio,
        min_price=min_price,
        min_turnover_cr=min_turnover_cr,
        require_above_200dma=require_above_200dma,
        rsi_filter_enabled=rsi_filter_enabled,
        rsi_threshold=rsi_threshold,
    )

    symbols = get_all_symbols()
    breakouts = []

    def _scan():
        for symbol in symbols:
            try:
                df = get_stock_data_with_indicators(symbol, config)
                if df.empty or len(df) < 252:
                    continue

                # Evaluate the latest bar
                idx = len(df) - 1
                result = evaluate_breakout(df, idx, config)

                if result and result["is_breakout"]:
                    info = get_stock_info(symbol) or {}
                    breakout = {
                        "symbol": symbol,
                        "company": info.get("company", ""),
                        "industry": info.get("industry", ""),
                        "scan_date": df.index[-1].strftime("%Y-%m-%d"),
                        **result,
                    }
                    breakouts.append(breakout)

            except Exception as e:
                logger.error(f"Scan error for {symbol}: {e}")

        # Sort by strength score descending
        breakouts.sort(key=lambda x: x.get("strength_score", 0), reverse=True)

        # Save to database
        scan_date = datetime.now().strftime("%Y-%m-%d")
        save_scan_results([
            {**b, "scan_date": scan_date}
            for b in breakouts
        ])

        return breakouts

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(executor, _scan)

    return sanitize_for_json({
        "breakouts": result,
        "total": len(result),
        "scanned": len(symbols),
        "config": config.to_dict(),
    })


# ─── Single Stock Detail ────────────────────────────────────────────────────

@app.get("/api/stock/{symbol}")
async def stock_detail(symbol: str):
    """Get detailed data for a single stock."""
    info = get_stock_info(symbol.upper())
    if not info:
        raise HTTPException(status_code=404, detail=f"Stock {symbol} not found")

    config = ScreenerConfig()

    def _get_detail():
        df = get_stock_data_with_indicators(symbol.upper(), config)
        if df.empty:
            return {"info": info, "data": None}

        # Get latest values
        latest = df.iloc[-1]
        latest_data = {
            "date": df.index[-1].strftime("%Y-%m-%d"),
            "close": round(float(latest["Close"]), 2),
            "volume": int(latest["Volume"]),
            "sma_200": round(float(latest["SMA_200"]), 2) if not pd.isna(latest.get("SMA_200")) else None,
            "sma_50": round(float(latest["SMA_50"]), 2) if not pd.isna(latest.get("SMA_50")) else None,
            "rsi": round(float(latest["RSI"]), 2) if not pd.isna(latest.get("RSI")) else None,
            "volume_ratio": round(float(latest["Volume_Ratio"]), 2) if not pd.isna(latest.get("Volume_Ratio")) else None,
            "avg_turnover_cr": round(float(latest["Avg_Turnover_Cr"]), 2) if not pd.isna(latest.get("Avg_Turnover_Cr")) else None,
            "high_52w": round(float(latest["High_52W"]), 2) if not pd.isna(latest.get("High_52W")) else None,
            "bb_width": round(float(latest["BB_Width"]), 2) if not pd.isna(latest.get("BB_Width")) else None,
        }

        # Check breakout status
        idx = len(df) - 1
        breakout = evaluate_breakout(df, idx, config)

        # Recent price history (last 30 days) for a mini chart
        recent = df.tail(30)[["Close", "Volume"]].copy()
        recent.index = recent.index.strftime("%Y-%m-%d")
        price_history = [
            {"date": d, "close": round(float(r["Close"]), 2), "volume": int(r["Volume"])}
            for d, r in recent.iterrows()
        ]

        return {
            "info": info,
            "latest": latest_data,
            "breakout": breakout,
            "price_history": price_history,
        }

    import pandas as pd
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(executor, _get_detail)
    return result


# ─── Serve Frontend ─────────────────────────────────────────────────────────

frontend_dir = os.path.join(BASE_DIR, "frontend")
if os.path.exists(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
