"""
Data acquisition layer.
Fetches OHLCV data from Yahoo Finance and caches it in SQLite.
Supports incremental updates — only downloads missing days.
"""

import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import logging
import time

from backend.config import ScreenerConfig, NIFTY500_CSV
from backend.database import (
    init_db,
    load_stocks_from_csv,
    get_all_symbols,
    upsert_ohlcv,
    get_last_cached_date,
    get_ohlcv,
    get_stock_info,
)

import os
import tempfile

logger = logging.getLogger(__name__)

# Set yfinance timezone cache location to temp directory to avoid permissions/existence issues on Render/Cloud
try:
    tz_dir = os.path.join(tempfile.gettempdir(), "py-yfinance")
    os.makedirs(tz_dir, exist_ok=True)
    yf.set_tz_cache_location(tz_dir)
except Exception:
    pass


def initialize_stock_universe():
    """
    Initialize the database and load the Nifty 500 stock list.
    Call this once on first run or when refreshing the universe.
    """
    init_db()
    count = load_stocks_from_csv(NIFTY500_CSV)
    logger.info(f"Loaded {count} stocks into database")
    return count


def fetch_single_stock(symbol: str, period: str = "2y") -> pd.DataFrame:
    """
    Fetch OHLCV data for a single stock from Yahoo Finance.

    Args:
        symbol: NSE ticker symbol (without .NS suffix)
        period: yfinance period string (e.g., '2y', '1y', '6mo')

    Returns:
        DataFrame with OHLCV data, or empty DataFrame on error.
    """
    ticker = f"{symbol}.NS"
    try:
        data = yf.download(ticker, period=period, progress=False, auto_adjust=True)
        if data.empty:
            logger.warning(f"No data returned for {ticker}")
            return pd.DataFrame()

        # yf.download with single ticker returns flat columns
        # but sometimes returns MultiIndex — handle both cases
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)

        # Ensure standard column names
        rename_map = {}
        for col in data.columns:
            col_lower = str(col).lower()
            if "open" in col_lower:
                rename_map[col] = "Open"
            elif "high" in col_lower:
                rename_map[col] = "High"
            elif "low" in col_lower:
                rename_map[col] = "Low"
            elif "close" in col_lower:
                rename_map[col] = "Close"
            elif "volume" in col_lower:
                rename_map[col] = "Volume"
        if rename_map:
            data = data.rename(columns=rename_map)

        # Keep only OHLCV columns
        needed = ["Open", "High", "Low", "Close", "Volume"]
        available = [c for c in needed if c in data.columns]
        data = data[available]

        return data

    except Exception as e:
        logger.error(f"Error fetching {ticker}: {e}")
        return pd.DataFrame()


def sync_stock(symbol: str, period: str = "2y") -> int:
    """
    Sync a single stock's data — fetch from yfinance and cache in SQLite.
    Uses incremental updates if data already exists.

    Returns:
        Number of new rows added.
    """
    last_date = get_last_cached_date(symbol)

    if last_date:
        # Incremental update: only fetch from last cached date
        last_dt = pd.to_datetime(last_date)
        today = pd.Timestamp.now().normalize()

        # If we already have today's data, skip
        if last_dt >= today - timedelta(days=1):
            return 0

        # Fetch from last cached date + 1 day
        start_date = (last_dt + timedelta(days=1)).strftime("%Y-%m-%d")
        end_date = today.strftime("%Y-%m-%d")

        ticker = f"{symbol}.NS"
        try:
            data = yf.download(
                ticker, start=start_date, end=end_date, progress=False, auto_adjust=True
            )
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.get_level_values(0)

            # Normalize column names
            rename_map = {}
            for col in data.columns:
                col_lower = str(col).lower()
                if "open" in col_lower:
                    rename_map[col] = "Open"
                elif "high" in col_lower:
                    rename_map[col] = "High"
                elif "low" in col_lower:
                    rename_map[col] = "Low"
                elif "close" in col_lower:
                    rename_map[col] = "Close"
                elif "volume" in col_lower:
                    rename_map[col] = "Volume"
            if rename_map:
                data = data.rename(columns=rename_map)

        except Exception as e:
            logger.error(f"Error in incremental sync for {symbol}: {e}")
            data = pd.DataFrame()
    else:
        # Full download
        data = fetch_single_stock(symbol, period=period)

    if data.empty:
        return 0

    needed = ["Open", "High", "Low", "Close", "Volume"]
    available = [c for c in needed if c in data.columns]
    data = data[available]

    return upsert_ohlcv(symbol, data)


def sync_all_stocks(
    symbols: list = None,
    period: str = "2y",
    progress_callback=None,
    batch_size: int = 20,
) -> dict:
    """
    Sync OHLCV data for all stocks (or a subset).
    Uses batch downloading with small batch sizes and rate-limit safeguards for cloud deployment.
    """
    if symbols is None:
        symbols = get_all_symbols()

    if not symbols:
        initialize_stock_universe()
        symbols = get_all_symbols()

    total = len(symbols)
    synced = 0
    failed = 0
    skipped = 0
    total_rows = 0

    # Check which symbols need full download vs incremental update
    needs_full = []
    needs_incremental = []

    for sym in symbols:
        last_date = get_last_cached_date(sym)
        if last_date:
            needs_incremental.append(sym)
        else:
            needs_full.append(sym)

    # --- Batch download for symbols needing full data ---
    if needs_full:
        if progress_callback:
            progress_callback(0, total, f"Downloading {len(needs_full)} new stocks...")

        # Process in smaller batches (20 stocks) to avoid rate limits on cloud IPs
        for batch_start in range(0, len(needs_full), batch_size):
            batch = needs_full[batch_start : batch_start + batch_size]
            tickers = [f"{s}.NS" for s in batch]

            try:
                # Use threads=False on cloud servers to avoid triggering IP rate limits
                batch_data = yf.download(
                    tickers, period=period, progress=False, auto_adjust=True,
                    group_by="ticker", threads=False,
                )

                for sym in batch:
                    ticker = f"{sym}.NS"
                    try:
                        if len(tickers) == 1:
                            stock_data = batch_data
                        else:
                            stock_data = batch_data[ticker] if ticker in batch_data.columns.get_level_values(0) else pd.DataFrame()

                        if isinstance(stock_data, pd.DataFrame) and not stock_data.empty:
                            if isinstance(stock_data.columns, pd.MultiIndex):
                                stock_data.columns = stock_data.columns.get_level_values(0)

                            rename_map = {}
                            for col in stock_data.columns:
                                col_lower = str(col).lower()
                                if "open" in col_lower:
                                    rename_map[col] = "Open"
                                elif "high" in col_lower:
                                    rename_map[col] = "High"
                                elif "low" in col_lower:
                                    rename_map[col] = "Low"
                                elif "close" in col_lower:
                                    rename_map[col] = "Close"
                                elif "volume" in col_lower:
                                    rename_map[col] = "Volume"
                            if rename_map:
                                stock_data = stock_data.rename(columns=rename_map)

                            needed = ["Open", "High", "Low", "Close", "Volume"]
                            available = [c for c in needed if c in stock_data.columns]
                            stock_data = stock_data[available].dropna(how="all")

                            rows = upsert_ohlcv(sym, stock_data)
                            total_rows += rows
                            synced += 1
                        else:
                            failed += 1
                    except Exception as e:
                        logger.error(f"Error processing {sym} from batch: {e}")
                        failed += 1

            except Exception as e:
                logger.error(f"Batch download error (rate limit?): {e}. Retrying individually with pauses...")
                time.sleep(2.0)
                # Fallback to individual downloads with pauses
                for sym in batch:
                    try:
                        rows = sync_stock(sym, period)
                        total_rows += rows
                        if rows > 0:
                            synced += 1
                        else:
                            failed += 1
                        time.sleep(0.5)
                    except Exception as e2:
                        logger.error(f"Individual download error for {sym}: {e2}")
                        failed += 1

            if progress_callback:
                done = min(batch_start + batch_size, len(needs_full))
                progress_callback(
                    done,
                    total,
                    f"Downloaded {done}/{len(needs_full)} new stocks..."
                )

            # Pause between batches to respect rate limits
            time.sleep(1.0)

    # --- Incremental updates ---
    if needs_incremental:
        if progress_callback:
            progress_callback(
                len(needs_full), total,
                f"Updating {len(needs_incremental)} cached stocks..."
            )

        for i, sym in enumerate(needs_incremental):
            try:
                rows = sync_stock(sym, period)
                total_rows += rows
                if rows > 0:
                    synced += 1
                else:
                    skipped += 1
            except Exception as e:
                logger.error(f"Incremental sync error for {sym}: {e}")
                failed += 1

            if progress_callback and (i + 1) % 10 == 0:
                progress_callback(
                    len(needs_full) + i + 1, total,
                    f"Updated {i + 1}/{len(needs_incremental)} stocks..."
                )

    if progress_callback:
        progress_callback(total, total, "Sync complete!")

    return {
        "total": total,
        "synced": synced,
        "failed": failed,
        "skipped": skipped,
        "total_rows_added": total_rows,
    }


def get_stock_data_with_indicators(
    symbol: str, config: ScreenerConfig = None
) -> pd.DataFrame:
    """
    Get a stock's OHLCV data from cache with all indicators computed.

    Args:
        symbol: NSE ticker symbol
        config: Screener configuration

    Returns:
        DataFrame with OHLCV + all indicator columns.
    """
    from backend.indicators import compute_all_indicators

    if config is None:
        config = ScreenerConfig()

    df = get_ohlcv(symbol)
    if df.empty:
        return df

    df = compute_all_indicators(df, config)
    return df
