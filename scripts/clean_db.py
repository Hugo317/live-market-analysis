"""One-off maintenance pass: apply data_handling.clean's OHLC sanity checks to
rows already sitting in market_data.db (rows inserted before that check
existed). Purely local -- reads/writes the DB only, never touches an API.

Usage:
    uv run python scripts/clean_db.py
"""

import pandas as pd

from live_market_analysis.data_handling.clean import fix_ohlc
from live_market_analysis.data_handling.db import get_connection


def main() -> None:
    with get_connection() as conn:
        df = pd.read_sql_query("SELECT rowid, region, symbol, timestamp, open, high, low, close FROM quotes", conn)
        print(f"Loaded {len(df)} rows.")

        fixed = fix_ohlc(df)
        dropped_rowids = df.loc[~df.index.isin(fixed.index), "rowid"].tolist()

        changed = fixed[(fixed["high"] != df.loc[fixed.index, "high"]) | (fixed["low"] != df.loc[fixed.index, "low"])]

        print(f"Dropping {len(dropped_rowids)} rows (non-positive price or >{50}% OHLC deviation).")
        print(f"Normalizing high/low on {len(changed)} rows (rounding-level OHLC inconsistency).")

        cur = conn.cursor()
        cur.executemany("DELETE FROM quotes WHERE rowid = ?", [(r,) for r in dropped_rowids])
        cur.executemany(
            "UPDATE quotes SET high = ?, low = ? WHERE rowid = ?",
            list(zip(changed["high"], changed["low"], changed["rowid"])),
        )
        conn.commit()

    print("Done.")


if __name__ == "__main__":
    main()
