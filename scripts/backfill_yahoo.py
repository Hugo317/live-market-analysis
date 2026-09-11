"""Supplementary deep-history backfill via Yahoo Finance (yfinance).

Unofficial endpoint: no API key, no documented quota, but also no uptime/
rate-limit guarantee -- see CLAUDE.md and apis/yahoo.py. This is what fills
in the history EODHD's (~1yr) and iTick's (~440 bar) free tiers can't reach;
it does not replace fetch_bulk_historical/backfill_all, which remain the
primary quota-tracked sources.

Usage:
    uv run python scripts/backfill_yahoo.py
"""

from live_market_analysis import fetch_raw
from live_market_analysis.data_handling.clean import clean
from live_market_analysis.data_handling.db import upsert_quotes
from live_market_analysis.data_handling.merge import merge_quotes
from live_market_analysis.data_handling.symbols import (
    get_asia_pairs,
    get_europe_symbols,
    get_us_symbols,
)


def main() -> None:
    eodhd_symbols = get_europe_symbols()
    us_symbols = get_us_symbols()
    asia_pairs = get_asia_pairs()

    print(
        f"Backfilling max-history via Yahoo Finance for {len(eodhd_symbols)} EU + "
        f"{len(us_symbols)} US + {len(asia_pairs)} Asia symbols."
    )
    results = fetch_raw.backfill_yahoo(eodhd_symbols, us_symbols, asia_pairs)

    for key, status in results.items():
        print(f"  {key}: {status}")

    print("\nMerging + persisting to the database...")
    upsert_quotes(clean(merge_quotes()))
    print("Done.")


if __name__ == "__main__":
    main()
