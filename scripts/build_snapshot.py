"""Build the small static snapshot the deployed dashboard reads.

Reads the full local `market_data.db` (gitignored, ~1 GB) and writes
`data/snapshot.db`: the last N years of *daily* bars per symbol, in the same
schema, so the dashboard code is identical either way. No API is called.

Intraday bars are collapsed to one bar per symbol per day, and `change` /
`change_pct` are recomputed bar-over-bar on the collapsed series.

Usage:
    uv run python scripts/build_snapshot.py [years]    # default 3
"""

import sqlite3
import sys

import pandas as pd

from live_market_analysis.data_handling.db import COLUMNS, CREATE_TABLE_SQL, FULL_DB_PATH, SNAPSHOT_PATH


def main(years: int = 3) -> None:
    if not FULL_DB_PATH.exists():
        raise SystemExit(f"{FULL_DB_PATH} not found; the snapshot is built from the full database.")

    with sqlite3.connect(FULL_DB_PATH) as src:
        latest = pd.to_datetime(src.execute("SELECT MAX(timestamp) FROM quotes").fetchone()[0], format="mixed")
        cutoff = (latest - pd.DateOffset(years=years)).strftime("%Y-%m-%d")
        df = pd.read_sql_query("SELECT * FROM quotes WHERE timestamp >= ?", src, params=(cutoff,))

    df["timestamp"] = pd.to_datetime(df["timestamp"], format="mixed")
    df["day"] = df["timestamp"].dt.normalize()
    df = df.sort_values(["region", "symbol", "timestamp"])

    daily = (
        df.groupby(["region", "symbol", "day"], sort=False)
        .agg(
            timestamp=("timestamp", "last"),
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
        )
        .reset_index()
        .drop(columns="day")
        .sort_values(["region", "symbol", "timestamp"])
    )

    prev_close = daily.groupby(["region", "symbol"])["close"].shift()
    daily["change"] = daily["close"] - prev_close
    daily["change_pct"] = daily["change"] / prev_close * 100

    out = daily[COLUMNS].copy()
    out["timestamp"] = out["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")

    SNAPSHOT_PATH.parent.mkdir(exist_ok=True)
    SNAPSHOT_PATH.unlink(missing_ok=True)
    with sqlite3.connect(SNAPSHOT_PATH) as dst:
        # WITHOUT ROWID stores the table as its primary-key index, about half the size.
        dst.execute(CREATE_TABLE_SQL.rstrip().rstrip(";") + " WITHOUT ROWID")
        dst.executemany(
            f"INSERT INTO quotes ({', '.join(COLUMNS)}) VALUES ({', '.join('?' for _ in COLUMNS)})",
            out.astype(object).where(out.notna(), None).itertuples(index=False, name=None),
        )
    with sqlite3.connect(SNAPSHOT_PATH) as dst:
        dst.execute("VACUUM")

    print(f"{len(out):,} rows, {out['symbol'].nunique()} symbols, {cutoff} to {latest:%Y-%m-%d} -> {SNAPSHOT_PATH}")
    print(f"{SNAPSHOT_PATH.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 3)
