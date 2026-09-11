---
name: raw-contract-history
description: History of data/raw/*.json shape changes and provider bar field names, so future sessions don't assume a stale contract
metadata:
  type: project
---

The project moved from a live/current-quote dashboard to a historical-only dashboard (fetched once/day for US+Asia bulk, on-demand for Europe) because of tight free-tier API quotas. `fetch_raw.py` (owned by api-info-manager) was rewritten accordingly, changing the `data/raw/*.json` contract:

- Old shape: flat list of single current-quote dicts per provider.
- New shape (as of 2026-09-11): dict keyed by symbol (eodhd, twelve_data) or `"REGION:CODE"` (itick), mapping to a list of historical bars (itick additionally wraps its list in `{"data": [...]}`).

Provider bar field names (confirmed from `apis/*.py` `get_historical()` and pre-existing usage in `analyze.py`):
- eodhd: `date`, `open`, `high`, `low`, `close`, `volume`. Oldest -> newest order.
- twelve_data: `datetime`, `open`, `high`, `low`, `close`, `volume` (numeric fields are strings, need casting). Newest -> oldest order as returned/stored — must reverse before diffing/plotting.
- itick: `t` (ms epoch), `o`, `h`, `l`, `c`, `v`. Oldest -> newest order.

**Why this matters:** `merge.py`'s `_normalize_*` functions must match whatever `fetch_raw.py` currently writes — always re-check `fetch_raw.py`'s actual output shape (or ask api-info-manager) rather than trusting an old memory of the contract, since this has already changed once and could change again as quota constraints evolve. See [[testing-merge-safely]] for how to verify changes without live API calls.

`change`/`change_pct` are not present in raw historical bars (unlike the old live-quote payloads, which had them for free) and must be computed bar-over-bar within each symbol's own oldest->newest series: `change = close - prev_close`, `change_pct = change / prev_close * 100`, with the first bar per symbol getting `None`/NaN (fine — `clean.py`'s `REQUIRED_COLUMNS` don't include them, so those rows survive `dropna`).
