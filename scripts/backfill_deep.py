"""Maximum-growth backfill: multi-granularity Yahoo Finance (no quota) plus
extra weekly/monthly bars from Twelve Data + iTick (using quota they still
have left today). EODHD/Europe is deliberately excluded here -- its free
tier caps out around 1yr of history regardless of period, and its
20-calls/day budget is typically already spent by scripts/backfill_db.py.

WARNING: this makes real API calls (count scales with the tracked symbol
universe -- see the printed totals when it starts). Do not run without
explicit user confirmation -- see CLAUDE.md.

Usage:
    uv run python scripts/backfill_deep.py
"""

import sys

from live_market_analysis import fetch_raw
from live_market_analysis.data_handling.clean import clean
from live_market_analysis.data_handling.db import upsert_quotes
from live_market_analysis.data_handling.merge import merge_quotes
from live_market_analysis.data_handling.symbols import (
    get_asia_pairs,
    get_europe_symbols,
    get_us_symbols,
)


def _progress_bar(label: str, width: int = 30):
    def _report(done: int, total: int, current: str) -> None:
        filled = int(width * done / total) if total else width
        bar = "█" * filled + "░" * (width - filled)
        sys.stdout.write(f"\r{label} [{bar}] {done}/{total}  {current[:40]:<40}")
        sys.stdout.flush()
        if done == total:
            sys.stdout.write("\n")

    return _report


def main() -> None:
    eodhd_symbols = get_europe_symbols()
    us_symbols = get_us_symbols()
    asia_pairs = get_asia_pairs()

    total_yahoo = (len(eodhd_symbols) + len(us_symbols) + len(asia_pairs)) * len(fetch_raw.YAHOO_DEEP_INTERVALS)
    print(
        f"Yahoo deep multi-interval backfill: {len(eodhd_symbols)} EU + {len(us_symbols)} US + "
        f"{len(asia_pairs)} Asia symbols x {len(fetch_raw.YAHOO_DEEP_INTERVALS)} intervals = {total_yahoo} calls"
    )
    yahoo_results = fetch_raw.backfill_yahoo_deep(
        eodhd_symbols, us_symbols, asia_pairs, on_progress=_progress_bar("Yahoo  ")
    )
    ok = sum(1 for v in yahoo_results.values() if v.startswith("ok"))
    print(f"  {ok}/{len(yahoo_results)} combos ok")
    for key, status in yahoo_results.items():
        if not status.startswith("ok"):
            print(f"  {key}: {status}")

    total_extra = (len(us_symbols) + len(asia_pairs)) * 2
    print(f"\nExtra weekly/monthly bars for Twelve Data (US) + iTick (Asia) = {total_extra} calls")
    extra_results = fetch_raw.backfill_extra_periods(
        us_symbols, asia_pairs, on_progress=_progress_bar("Extra  ")
    )
    ok = sum(1 for v in extra_results.values() if v.startswith("ok"))
    print(f"  {ok}/{len(extra_results)} combos ok")
    for key, status in extra_results.items():
        if not status.startswith("ok"):
            print(f"  {key}: {status}")

    print("\nMerging + persisting to the database...")
    upsert_quotes(clean(merge_quotes()))
    print("Done.")


if __name__ == "__main__":
    main()
