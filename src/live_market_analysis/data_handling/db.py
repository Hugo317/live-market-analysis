import sqlite3
from pathlib import Path

import pandas as pd

DB_PATH = Path(__file__).resolve().parents[3] / "market_data.db"

COLUMNS = ["region", "symbol", "timestamp", "open", "high", "low", "close", "volume", "change", "change_pct"]

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS quotes (
    region TEXT NOT NULL,
    symbol TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume REAL,
    change REAL,
    change_pct REAL,
    PRIMARY KEY (region, symbol, timestamp)
)
"""


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(CREATE_TABLE_SQL)
    return conn


def upsert_quotes(df: pd.DataFrame) -> None:
    rows = df[COLUMNS].copy()
    rows["timestamp"] = rows["timestamp"].astype(str)

    with get_connection() as conn:
        conn.executemany(
            f"""
            INSERT OR REPLACE INTO quotes ({", ".join(COLUMNS)})
            VALUES ({", ".join("?" for _ in COLUMNS)})
            """,
            rows.itertuples(index=False, name=None),
        )


def _read(query: str, params: tuple = ()) -> pd.DataFrame:
    with get_connection() as conn:
        df = pd.read_sql_query(query, conn, params=params)
    if "timestamp" in df.columns:
        # Not done via read_sql_query's own `parse_dates` -- that infers a
        # single format from the column and silently turns non-matching rows
        # into NaT. The `timestamp` column legitimately mixes formats
        # (whole-second bars from most providers vs fractional-second bars
        # from some iTick pulls), so each value needs its own format
        # inferred; format="mixed" does that instead of locking onto
        # whichever format the first row happens to use.
        df["timestamp"] = pd.to_datetime(df["timestamp"], format="mixed")
    return df


def read_quotes(region: str | None = None) -> pd.DataFrame:
    """Full historical rows -- every bar, every symbol (or every symbol in
    `region`). Expensive at this table's size (millions of rows); prefer
    `read_latest_quotes`/`read_recent_bars`/`read_symbol_history` below for
    dashboard views that don't need the whole table."""
    query = "SELECT * FROM quotes"
    params = ()
    if region:
        query += " WHERE region = ?"
        params = (region,)
    return _read(query, params)


def read_latest_quotes(region: str | None = None) -> pd.DataFrame:
    """Just the most recent bar per (region, symbol) -- computed as a
    GROUP BY MAX(timestamp) self-join rather than a window function. SQLite
    can answer `GROUP BY region, symbol` with a pure index scan over the
    (region, symbol, timestamp) primary key (it's already sorted that way,
    so MAX per group falls out of the scan for free); a window function over
    the same PK forces it to materialize and rank every row in the partition
    instead, which is far slower at this table's size (millions of rows).
    This is what "current standing" dashboard views (top gainers/volume/
    volatility, region growth, hero stats) actually need. Timestamps mix
    formats (see `_read`) but all share the same fixed-width leading
    "YYYY-MM-DD HH:MM:SS" prefix, so plain TEXT MAX is chronologically
    correct here.
    """
    where = "WHERE region = ?" if region else ""
    query = f"""
        SELECT q.region, q.symbol, q.timestamp, q.open, q.high, q.low, q.close, q.volume, q.change, q.change_pct
        FROM quotes q
        JOIN (
            SELECT region, symbol, MAX(timestamp) AS max_ts
            FROM quotes
            {where}
            GROUP BY region, symbol
        ) latest
        ON q.region = latest.region AND q.symbol = latest.symbol AND q.timestamp = latest.max_ts
    """
    params = (region,) if region else ()
    return _read(query, params)


def read_recent_bars(region: str, symbols: list[str], limit_per_symbol: int = 15) -> pd.DataFrame:
    """The most recent `limit_per_symbol` bars for each of `symbols` in
    `region` -- enough for a sparkline, without loading each symbol's entire
    history. One small `LIMIT`-bounded, index-seek query per symbol (a plain
    `ORDER BY timestamp DESC LIMIT n` on the (region, symbol, timestamp)
    primary key needs no sort or full-partition scan) rather than one
    window-function pass over the whole region, which -- unlike
    `read_latest_quotes`'s GROUP BY MAX -- has no equivalent cheap
    index-only form and was the dashboard's actual bottleneck (~5s for a
    200-symbol region) before this.
    """
    if not symbols:
        return pd.DataFrame(columns=["region", "symbol", "timestamp", "close"])

    frames = []
    with get_connection() as conn:
        for symbol in symbols:
            frames.append(
                pd.read_sql_query(
                    """
                    SELECT region, symbol, timestamp, close FROM quotes
                    WHERE region = ? AND symbol = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    conn,
                    params=(region, symbol, limit_per_symbol),
                )
            )
    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["region", "symbol", "timestamp", "close"])
    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"], format="mixed")
    return df


def read_symbol_history(region: str, symbol: str) -> pd.DataFrame:
    """Full history for exactly one (region, symbol) -- what the trend chart
    needs, without loading every other symbol's rows to filter in pandas."""
    query = "SELECT * FROM quotes WHERE region = ? AND symbol = ? ORDER BY timestamp"
    return _read(query, (region, symbol))


if __name__ == "__main__":
    from live_market_analysis.data_handling.clean import clean
    from live_market_analysis.data_handling.merge import merge_quotes

    raw = merge_quotes(
        eodhd_symbols=["VOD.LSE"],
        twelve_data_symbols=["AAPL"],
        itick_pairs=[("HK", "700")],
    )
    upsert_quotes(clean(raw))
    print(read_quotes())
