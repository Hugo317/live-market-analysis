---
name: testing-merge-safely
description: How to validate merge.py/clean.py/analyze.py changes without corrupting real data/raw files or calling live APIs
metadata:
  type: feedback
---

When `data/raw/*.json` exists but is in an old/different shape than what the code being tested expects (e.g. during a contract migration), don't overwrite it in place and forget to restore it. Pattern that worked:

1. Copy the real `data/raw/*.json` files to the scratchpad dir as a backup.
2. Write synthetic fixture JSON (matching the *new* contract being implemented) directly into `data/raw/*.json`.
3. Run `merge_quotes()`/`clean()` against the synthetic fixtures to verify logic.
4. Copy the backups back over `data/raw/*.json` immediately after.
5. Verify with `git status --short data/raw/` that nothing changed (it's gitignored/untracked here, so this only confirms file contents match, not that git sees no diff — compare timestamps/content directly if in doubt).

**Why:** `data/raw/*.json` is real fetched data (costs API quota to regenerate, e.g. EODHD is capped at 20 calls/day) and is owned by `fetch_raw.py`/api-info-manager, not the data-handler agent — never leave it mutated or in a stale/half-migrated state after a test.

Also: running these modules via bare `python3` fails with `ModuleNotFoundError: No module named 'dotenv'` because the project's deps live in a uv-managed venv — use `uv run python ...` or `uv run python -m live_market_analysis....` instead.
