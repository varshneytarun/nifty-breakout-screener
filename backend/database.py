"""
SQLite database setup and CRUD operations.
Uses Python's built-in sqlite3 — no ORM, no extra dependencies.
"""

import sqlite3
import os
import pandas as pd
from backend.config import DB_PATH, DATA_DIR


def get_connection() -> sqlite3.Connection:
    """Get a database connection. Creates the data directory if needed."""
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # Better concurrent read performance
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create all tables if they don't exist, and seed from screener_seed.db if fresh."""
    os.makedirs(DATA_DIR, exist_ok=True)
    seed_db = os.path.join(DATA_DIR, "screener_seed.db")
    if not os.path.exists(DB_PATH) and os.path.exists(seed_db):
        import shutil
        try:
            shutil.copy2(seed_db, DB_PATH)
        except Exception:
            pass

    conn = get_connection()
    cursor = conn.cursor()

    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS stocks (
            symbol      TEXT PRIMARY KEY,
            company     TEXT,
            industry    TEXT,
            series      TEXT
        );

        CREATE TABLE IF NOT EXISTS ohlcv (
            symbol  TEXT NOT NULL,
            date    TEXT NOT NULL,
            open    REAL,
            high    REAL,
            low     REAL,
            close   REAL,
            volume  INTEGER,
            PRIMARY KEY (symbol, date)
        );

        CREATE TABLE IF NOT EXISTS backtest_signals (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_date     TEXT NOT NULL,
            symbol          TEXT NOT NULL,
            resistance_mode TEXT,
            resistance_level REAL,
            close_price     REAL,
            pct_above       REAL,
            volume_ratio    REAL,
            rsi             REAL,
            above_200dma    INTEGER,
            strength_score  INTEGER,
            return_5d       REAL,
            return_10d      REAL,
            return_20d      REAL,
            return_30d      REAL
        );

        CREATE TABLE IF NOT EXISTS scan_results (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_date       TEXT NOT NULL,
            symbol          TEXT NOT NULL,
            resistance_mode TEXT,
            resistance_level REAL,
            close_price     REAL,
            pct_above       REAL,
            volume_ratio    REAL,
            rsi             REAL,
            above_200dma    INTEGER,
            strength_score  INTEGER
        );

        CREATE INDEX IF NOT EXISTS idx_ohlcv_symbol ON ohlcv(symbol);
        CREATE INDEX IF NOT EXISTS idx_ohlcv_date ON ohlcv(date);
        CREATE INDEX IF NOT EXISTS idx_backtest_date ON backtest_signals(signal_date);
        CREATE INDEX IF NOT EXISTS idx_backtest_symbol ON backtest_signals(symbol);
        CREATE INDEX IF NOT EXISTS idx_scan_date ON scan_results(scan_date);
    """)

    conn.commit()
    conn.close()


def load_stocks_from_csv(csv_path: str):
    """Load stock universe from CSV into the stocks table."""
    df = pd.read_csv(csv_path)

    # Normalize column names
    col_map = {}
    for col in df.columns:
        lower = col.strip().lower()
        if "symbol" in lower:
            col_map[col] = "symbol"
        elif "company" in lower or "name" in lower:
            col_map[col] = "company"
        elif "industry" in lower:
            col_map[col] = "industry"
        elif "series" in lower:
            col_map[col] = "series"
    df = df.rename(columns=col_map)

    conn = get_connection()
    cursor = conn.cursor()

    for _, row in df.iterrows():
        cursor.execute(
            """
            INSERT OR REPLACE INTO stocks (symbol, company, industry, series)
            VALUES (?, ?, ?, ?)
            """,
            (
                row.get("symbol", "").strip(),
                row.get("company", "").strip(),
                row.get("industry", "").strip(),
                row.get("series", "EQ").strip(),
            ),
        )

    conn.commit()
    conn.close()
    return len(df)


def get_all_symbols() -> list:
    """Get all stock symbols from the database."""
    conn = get_connection()
    rows = conn.execute("SELECT symbol FROM stocks WHERE series = 'EQ' ORDER BY symbol").fetchall()
    conn.close()
    return [r["symbol"] for r in rows]


def get_stock_info(symbol: str) -> dict:
    """Get stock info (company name, industry, etc.)."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM stocks WHERE symbol = ?", (symbol,)).fetchone()
    conn.close()
    if row:
        return dict(row)
    return None


def upsert_ohlcv(symbol: str, df: pd.DataFrame):
    """
    Insert or update OHLCV data for a symbol.
    DataFrame must have a DatetimeIndex and columns: Open, High, Low, Close, Volume.
    """
    if df.empty:
        return 0

    conn = get_connection()
    cursor = conn.cursor()
    count = 0

    for date, row in df.iterrows():
        date_str = date.strftime("%Y-%m-%d") if hasattr(date, "strftime") else str(date)[:10]
        cursor.execute(
            """
            INSERT OR REPLACE INTO ohlcv (symbol, date, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                symbol,
                date_str,
                float(row["Open"]) if pd.notna(row["Open"]) else None,
                float(row["High"]) if pd.notna(row["High"]) else None,
                float(row["Low"]) if pd.notna(row["Low"]) else None,
                float(row["Close"]) if pd.notna(row["Close"]) else None,
                int(row["Volume"]) if pd.notna(row["Volume"]) else None,
            ),
        )
        count += 1

    conn.commit()
    conn.close()
    return count


def get_ohlcv(symbol: str, start_date: str = None, end_date: str = None) -> pd.DataFrame:
    """
    Get OHLCV data for a symbol as a pandas DataFrame.
    Dates should be in 'YYYY-MM-DD' format.
    """
    conn = get_connection()

    query = "SELECT date, open, high, low, close, volume FROM ohlcv WHERE symbol = ?"
    params = [symbol]

    if start_date:
        query += " AND date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND date <= ?"
        params.append(end_date)

    query += " ORDER BY date ASC"

    df = pd.read_sql_query(query, conn, params=params)
    conn.close()

    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date")
        df.columns = ["Open", "High", "Low", "Close", "Volume"]

    return df


def get_last_cached_date(symbol: str) -> str:
    """Get the most recent date we have cached for a symbol."""
    conn = get_connection()
    row = conn.execute(
        "SELECT MAX(date) as last_date FROM ohlcv WHERE symbol = ?", (symbol,)
    ).fetchone()
    conn.close()
    return row["last_date"] if row and row["last_date"] else None


def get_cached_symbol_count() -> int:
    """Get count of symbols that have cached OHLCV data."""
    conn = get_connection()
    row = conn.execute("SELECT COUNT(DISTINCT symbol) as cnt FROM ohlcv").fetchone()
    conn.close()
    return row["cnt"] if row else 0


def get_data_status() -> dict:
    """Get overall data freshness status."""
    conn = get_connection()

    total_stocks = conn.execute("SELECT COUNT(*) as cnt FROM stocks").fetchone()["cnt"]
    cached_stocks = conn.execute("SELECT COUNT(DISTINCT symbol) as cnt FROM ohlcv").fetchone()["cnt"]
    latest_date = conn.execute("SELECT MAX(date) as dt FROM ohlcv").fetchone()["dt"]
    oldest_date = conn.execute("SELECT MIN(date) as dt FROM ohlcv").fetchone()["dt"]
    total_rows = conn.execute("SELECT COUNT(*) as cnt FROM ohlcv").fetchone()["cnt"]

    conn.close()

    return {
        "total_stocks": total_stocks,
        "cached_stocks": cached_stocks,
        "latest_date": latest_date,
        "oldest_date": oldest_date,
        "total_ohlcv_rows": total_rows,
    }


def save_backtest_signals(signals: list):
    """
    Save backtest signals to database.
    Each signal is a dict with keys matching the backtest_signals table columns.
    """
    if not signals:
        return

    conn = get_connection()
    cursor = conn.cursor()

    for s in signals:
        cursor.execute(
            """
            INSERT INTO backtest_signals
            (signal_date, symbol, resistance_mode, resistance_level, close_price,
             pct_above, volume_ratio, rsi, above_200dma, strength_score,
             return_5d, return_10d, return_20d, return_30d)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                s.get("signal_date"),
                s.get("symbol"),
                s.get("resistance_mode"),
                s.get("resistance_level"),
                s.get("close_price"),
                s.get("pct_above"),
                s.get("volume_ratio"),
                s.get("rsi"),
                s.get("above_200dma", 0),
                s.get("strength_score"),
                s.get("return_5d"),
                s.get("return_10d"),
                s.get("return_20d"),
                s.get("return_30d"),
            ),
        )

    conn.commit()
    conn.close()


def clear_backtest_signals():
    """Clear all backtest signals (before re-running backtest)."""
    conn = get_connection()
    conn.execute("DELETE FROM backtest_signals")
    conn.commit()
    conn.close()


def get_backtest_signals(
    limit: int = 500,
    offset: int = 0,
    sort_by: str = "strength_score",
    sort_dir: str = "DESC",
    symbol: str = None,
    min_score: int = None,
) -> list:
    """Get backtest signals with optional filtering and pagination."""
    conn = get_connection()

    # Validate sort column to prevent SQL injection
    valid_sorts = {
        "strength_score", "signal_date", "pct_above", "volume_ratio",
        "return_5d", "return_10d", "return_20d", "return_30d", "symbol",
    }
    if sort_by not in valid_sorts:
        sort_by = "strength_score"
    if sort_dir.upper() not in ("ASC", "DESC"):
        sort_dir = "DESC"

    query = """
        SELECT bs.*, s.company, s.industry
        FROM backtest_signals bs
        LEFT JOIN stocks s ON bs.symbol = s.symbol
        WHERE 1=1
    """
    params = []

    if symbol:
        query += " AND bs.symbol = ?"
        params.append(symbol)

    if min_score is not None:
        query += " AND bs.strength_score >= ?"
        params.append(min_score)

    query += f" ORDER BY bs.{sort_by} {sort_dir} LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    rows = conn.execute(query, params).fetchall()
    conn.close()

    return [dict(r) for r in rows]


def get_backtest_signal_count() -> int:
    """Get total count of backtest signals."""
    conn = get_connection()
    row = conn.execute("SELECT COUNT(*) as cnt FROM backtest_signals").fetchone()
    conn.close()
    return row["cnt"] if row else 0


def save_scan_results(results: list):
    """Save live scan results."""
    if not results:
        return

    conn = get_connection()
    cursor = conn.cursor()

    for r in results:
        cursor.execute(
            """
            INSERT INTO scan_results
            (scan_date, symbol, resistance_mode, resistance_level, close_price,
             pct_above, volume_ratio, rsi, above_200dma, strength_score)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                r.get("scan_date"),
                r.get("symbol"),
                r.get("resistance_mode"),
                r.get("resistance_level"),
                r.get("close_price"),
                r.get("pct_above"),
                r.get("volume_ratio"),
                r.get("rsi"),
                r.get("above_200dma", 0),
                r.get("strength_score"),
            ),
        )

    conn.commit()
    conn.close()
