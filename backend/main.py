"""
FastAPI application — serves the REST API and static frontend.
"""

import asyncio
import json
import logging
import math
from datetime import datetime, timezone, timedelta
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

# Track running operations and auto-sync state
_running_ops = {}
_auto_sync_state = {
    "is_syncing": False,
    "last_sync_time": None,
    "last_synced_date": None,
    "last_status": "Idle",
}


def get_expected_market_date() -> str:
    """
    Get expected latest trading date string (YYYY-MM-DD) in IST timezone.
    Indian markets trade Mon-Fri 09:15 to 15:30 IST.
    Daily candles are fully finalized after 18:00 IST (6 PM).
    """
    ist = timezone(timedelta(hours=5, minutes=30))
    now_ist = datetime.now(ist)

    # If today is weekday and after 18:00 IST, today's candle is expected.
    # Otherwise, target is previous trading day.
    if now_ist.weekday() < 5 and now_ist.hour >= 18:
        target_date = now_ist.date()
    else:
        # Step backward to find latest completed weekday
        target_date = now_ist.date() - timedelta(days=1)
        while target_date.weekday() >= 5:  # Saturday/Sunday -> move to Friday
            target_date -= timedelta(days=1)

    return target_date.strftime("%Y-%m-%d")


def check_and_run_auto_sync():
    """
    Background worker to check if data is outdated and run incremental sync.
    Runs periodically every 30 minutes and on startup.
    """
    global _auto_sync_state
    if _auto_sync_state["is_syncing"]:
        return

    try:
        expected_date = get_expected_market_date()
        status = get_data_status()
        latest_cached = status.get("latest_date")

        needs_sync = False
        if not latest_cached or status.get("cached_stocks", 0) == 0:
            needs_sync = True
        elif latest_cached < expected_date:
            needs_sync = True

        if needs_sync:
            ist = timezone(timedelta(hours=5, minutes=30))
            logger.info(f"🔄 Auto-sync triggered: latest cached is {latest_cached}, expected is {expected_date}")
            _auto_sync_state["is_syncing"] = True
            _auto_sync_state["last_status"] = f"Auto-refreshing data for {expected_date}..."

            result = sync_all_stocks()

            _auto_sync_state["is_syncing"] = False
            _auto_sync_state["last_sync_time"] = datetime.now(ist).isoformat()
            _auto_sync_state["last_synced_date"] = expected_date
            _auto_sync_state["last_status"] = f"Synced {result.get('synced', 0)} stocks (Latest: {expected_date})"
            logger.info(f"✅ Auto-sync completed successfully: {result}")
        else:
            _auto_sync_state["last_status"] = f"Up to date ({latest_cached})"

    except Exception as e:
        logger.error(f"❌ Auto-sync error: {e}")
        _auto_sync_state["is_syncing"] = False
        _auto_sync_state["last_status"] = f"Error: {str(e)}"


async def _daily_auto_sync_loop():
    """
    Background loop that runs every 30 minutes to check if the day changed / market closed
    and keep the stock database automatically refreshed at night.
    """
    logger.info("Auto-refresh background scheduler active (checks every 30 mins, refreshes when day changes/night)")
    while True:
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(executor, check_and_run_auto_sync)
        except Exception as e:
            logger.warning(f"Auto-sync loop warning: {e}")

        # Check every 30 minutes
        await asyncio.sleep(1800)


async def _keep_alive_loop():
    """Background loop to self-ping Render URL every 8 minutes and prevent 15-min sleep."""
    import urllib.request
    render_url = os.environ.get("RENDER_EXTERNAL_URL")
    if not render_url:
        return

    target = f"{render_url.rstrip('/')}/api/data/status"
    logger.info(f"Keep-alive loop active for {target}")

    while True:
        await asyncio.sleep(480)  # Ping every 8 minutes (Render spins down after 15 mins)
        try:
            req = urllib.request.Request(target, headers={"User-Agent": "RenderKeepAlive/1.0"})
            with urllib.request.urlopen(req, timeout=15) as res:
                logger.info(f"Keep-alive ping response: {res.status}")
        except Exception as e:
            logger.warning(f"Keep-alive ping notice: {e}")


@app.on_event("startup")
async def startup():
    """Initialize database and stock universe on startup, and launch background workers."""
    init_db()
    symbols = get_all_symbols()
    if not symbols:
        initialize_stock_universe()
        logger.info("Stock universe initialized")
    asyncio.create_task(_keep_alive_loop())
    asyncio.create_task(_daily_auto_sync_loop())



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
    min_rs_rating: float = None,
    require_vcp: bool = None,
    min_ai_prob: int = None,
    market_filter_enabled: bool = None,
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
    if min_rs_rating is not None:
        config.min_rs_rating = min_rs_rating
    if require_vcp is not None:
        config.require_vcp = require_vcp
    if min_ai_prob is not None:
        config.min_ai_prob = min_ai_prob
    if market_filter_enabled is not None:
        config.market_filter_enabled = market_filter_enabled
    return config


# ─── Market Regime & Sectors ────────────────────────────────────────────────

@app.get("/api/market-regime")
async def get_market_regime():
    """Get live Nifty 50 Market Regime indicator and trader guidance."""
    from backend.data_fetcher import get_benchmark_df
    from backend.indicators import calculate_market_regime
    benchmark_df = get_benchmark_df()
    regime = calculate_market_regime(benchmark_df)
    return sanitize_for_json(regime)


@app.get("/api/sectors")
async def get_sectors():
    """Get sector / industry momentum rankings."""
    from backend.data_fetcher import get_sector_momentum
    momentum = get_sector_momentum()
    return sanitize_for_json(momentum)


# ─── Config ─────────────────────────────────────────────────────────────────

@app.get("/api/config")
async def get_config():
    """Get default screener configuration."""
    return ScreenerConfig().to_dict()


# ─── Data Sync ──────────────────────────────────────────────────────────────

@app.get("/api/data/status")
async def data_status():
    """Check data freshness and auto-sync status."""
    status = get_data_status()
    status["auto_sync"] = _auto_sync_state
    status["expected_date"] = get_expected_market_date()
    return status


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
