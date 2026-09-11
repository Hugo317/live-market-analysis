---
name: historical-pipeline-migration
description: Project migrated from live-quote snapshots to multi-row-per-symbol historical bars; app.py must collapse to latest-per-symbol before feeding "current standing" views.
metadata:
  type: project
---

As of 2026-09-11, this project dropped the "live current quote" model entirely in favor of a
historical-only pipeline, driven by tight free-tier API quotas (EODHD 20 calls/day total
unbatched, Twelve Data 800/day + 8/min, iTick 5/min). Three agents split the work:

- `api-info-manager` owns `fetch_raw.py`: `fetch_bulk_historical(twelve_data_symbols, itick_pairs,
  period="d")` (US+Asia only, deliberately excludes EODHD/Europe — bulk-fetching ~20 EU symbols
  would blow the whole day's EODHD budget) and `fetch_symbol_historical(provider, *args,
  period="d")` (single-symbol on-demand fetch for any of the 3 providers, the *only* path allowed
  to call EODHD live). Both only write `data/raw/*.json` — they do **not** touch the DB. The
  caller must still run `merge_quotes()` → `clean()` → `upsert_quotes()` afterward.
- `data-handler` owns `merge.py`/`clean.py`/`analyze.py`: `merge_quotes()` now emits one row *per
  historical bar per symbol* (not one row per live quote), same column schema as before (`region,
  symbol, timestamp, open, high, low, close, volume, change, change_pct`), with change/change_pct
  computed bar-over-bar. This means `read_quotes()` can return many rows per symbol.
- `dashboard-builder` (me) owns `app.py`: must collapse to "most recent bar per symbol" before
  feeding `analyze.top_gainers`/`top_by_volume`/`top_volatility`/`region_growth`, or those rank
  individual historical bars instead of current standing.

As of this migration, `analyze.py` did **not** yet expose a `latest_per_symbol`-style helper. I
wrote `app.py`'s `_latest_per_symbol(df)` to prefer `analyze.latest_per_symbol` via `getattr` if it
exists, falling back to `df.sort_values("timestamp").groupby(["region","symbol"],
as_index=False).tail(1)` inline otherwise. Verify whether `analyze.latest_per_symbol` has since
landed — if so the getattr indirection can likely stay (harmless) or be simplified to a direct
call, but check `data_handling/analyze.py` before assuming either way (see [[latest-per-symbol-check]] if that
memory exists, otherwise grep `analyze.py` for `latest_per_symbol` fresh each time).
