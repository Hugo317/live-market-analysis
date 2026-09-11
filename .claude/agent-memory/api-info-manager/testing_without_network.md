---
name: testing-without-network
description: How to sanity-check fetch_raw.py logic without ever making a live API call
metadata:
  type: feedback
---

Hard rule for this project: never make a real (non-cached) API call without explicit user confirmation, and never run code to "verify" that would hit a live network API — not even to sanity-check a rewrite.

**How to verify fetch_raw.py changes safely**: stub out `live_market_analysis.apis.{eodhd,twelve_data,itick}` as fake modules in `sys.modules` with `get_historical` lambdas returning small fixture dicts, load `fetch_raw.py` via `importlib.util.spec_from_file_location` (so the real `apis` package with real network code is never imported), point `fetch_raw.RAW_DIR` at a temp dir, pre-seed one raw JSON file with an unrelated symbol, then call the public functions and assert (a) the new keys appear and (b) the pre-seeded unrelated key is still present (proves merge-not-clobber). This was used successfully to confirm the 2026-09-11 merge-write rewrite of `fetch_raw.py` without any network access.

Why: the previous flat-list `_save()` helper wrote whole-file overwrites; the historical-data redesign requires merge semantics (`_load` + `dict.update` + write back) because bulk daily fetches and on-demand single-symbol fetches both write to the same JSON files at different times and must not clobber each other.
