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


def read_quotes(region: str | None = None) -> pd.DataFrame:
    query = "SELECT * FROM quotes"
    params = ()
    if region:
        query += " WHERE region = ?"
        params = (region,)

    with get_connection() as conn:
        return pd.read_sql_query(query, conn, params=params, parse_dates=["timestamp"])


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
