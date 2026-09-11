---
name: quota-design
description: Why EODHD is excluded from bulk fetches and how fetch_raw.py's merge-write pattern works
metadata:
  type: project
---

The project dropped the live/current-quote view entirely (no more `get_quotes()` calls anywhere in the app flow) in favor of historical-only data, refreshed at most once/day or on demand. Driving constraint: EODHD (Europe) free tier is 20 calls/day total and `get_historical()` is unbatched (1 call per symbol). With ~20 FTSE symbols tracked, one bulk daily refresh would exhaust the entire day's EODHD budget.

**Design rule**: EODHD/Europe must never be bulk-fetched. It is only ever fetched one symbol at a time, via an explicit on-demand path (`fetch_symbol_historical("eodhd", symbol)`), triggered e.g. by a user picking a EU symbol in the dashboard trend chart. This mirrors the pre-existing exclusion in `analyze.py`'s "Growth by Period" feature for the same reason — check that feature if EODHD quota questions come up elsewhere.

Twelve Data (US, 800/day + 8/min) and iTick (Asia, 5/min via `rate_limiter.py`) have no such daily cap and are fine to bulk-fetch across all tracked symbols daily via `fetch_bulk_historical`.

**fetch_raw.py contract** (as of 2026-09-11 rewrite):
- `fetch_bulk_historical(twelve_data_symbols, itick_pairs, period="d")` — concurrent (ThreadPoolExecutor), writes/merges into `twelve_data.json` and `itick.json` only. Never touches `eodhd.json`.
- `fetch_symbol_historical(provider, *args, period="d")` — single-symbol on-demand, dispatch mirrors `analyze.get_symbol_history`'s calling convention (`"eodhd"`/`"twelve_data"` take `(symbol,)`, `"itick"` takes `(region, code)`). Only path allowed to call EODHD's `get_historical`.
- Raw JSON files use **merge-into-existing** semantics everywhere (read existing dict, `.update()` only the fetched keys, write back) — never wipe the whole file. This matters because on-demand single-symbol fetches and daily bulk fetches both write to the same files at different times.
- JSON shapes (contract with `data-handler`'s `merge.py`): `eodhd.json`/`twelve_data.json` are `{"<symbol>": [bar, ...]}` (raw bars as-is, EODHD oldest→newest, Twelve Data newest→oldest); `itick.json` is `{"<region>:<code>": {"data": [bar, ...]}}` (preserves the `data` wrapper, oldest→newest).

See also [[testing-without-network]] for how to verify fetch_raw.py changes without hitting live APIs.
