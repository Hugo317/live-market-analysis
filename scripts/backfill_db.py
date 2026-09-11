"""One-shot maximum-range historical backfill for all tracked symbols.

WARNING: this makes ~60 real API calls (one per tracked symbol across EODHD,
Twelve Data, and iTick) and uses EODHD's entire 20-calls/day free-tier budget
in a single run. Do not run this without explicit confirmation -- see the
quota table in CLAUDE.md.

Usage:
    uv run python scripts/backfill_db.py
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
    twelve_data_symbols = get_us_symbols()
    itick_pairs = get_asia_pairs()

    print(
        f"Backfilling {len(eodhd_symbols)} EU + {len(twelve_data_symbols)} US + "
        f"{len(itick_pairs)} Asia symbols. This makes real API calls."
    )
    results = fetch_raw.backfill_all(eodhd_symbols, twelve_data_symbols, itick_pairs)

    for provider, per_symbol in results.items():
        print(f"\n{provider}:")
        for symbol, status in per_symbol.items():
            print(f"  {symbol}: {status}")

    print("\nMerging + persisting to the database...")
    upsert_quotes(clean(merge_quotes()))
    print("Done.")


if __name__ == "__main__":
    main()
