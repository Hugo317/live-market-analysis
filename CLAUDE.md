# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Dash dashboard tracking **historical** stock market data across Europe (EODHD), the US (Twelve Data), and Asia (iTick), plus company/market news via yfinance. There is no live/current-quote view — `get_quotes()` is no longer called anywhere in the app flow. Data is fetched via `get_historical()`/`get_intraday()`: once a day in bulk for US + Asia, and on demand (one symbol at a time) for Europe and for any ad-hoc symbol lookup, to stay well inside each provider's free-tier quota.

## Setup and running

```
uv sync
cp .env.example .env   # then fill in EODHD_API_KEY, TWELVE_DATA_API_KEY, I_TICK_API_KEY
uv run python -m live_market_analysis.dashboard.app
```

Debug/reload mode: `DASHBOARD_DEBUG=true uv run python -m live_market_analysis.dashboard.app`

No linter, formatter, or test suite is configured yet (no ruff/black config, no pytest, no CI). Verification of changes is manual — see the `tester` subagent.

## API quota limits — critical, read before touching `apis/` or refresh logic

Never make a real (non-cached) API call without the user's explicit confirmation — this protects tight free-tier quotas.

| Provider | Free tier limit | Notes |
|---|---|---|
| EODHD (Europe) | **20 calls/day total**, not per-minute | Enforced via a daily counter in `.cache/eodhd_daily_calls.json` that raises before exceeding it. `get_historical()`/`get_intraday()` are not batched (1 call per symbol), so EODHD is **never** included in any bulk/automatic fetch — it's only ever fetched one symbol at a time, on demand, via `fetch_raw.fetch_symbol_historical("eodhd", symbol, ...)`. |
| Twelve Data (US) | 800 calls/day, 8 calls/min | No batch endpoint — `fetch_raw.fetch_bulk_historical()` loops one `get_historical()` call per US symbol (20 calls for a full daily US refresh). |
| iTick (Asia) | 5 calls/min | No confirmed daily cap. Loops one call per symbol; enforced via a sliding-window limiter (`data_handling/rate_limiter.py`). Must use `api-free.itick.org`, not `api.itick.org` — the latter rejects free-tier keys. |
| yfinance (news) | None (free, unauthenticated) | No special handling needed. |

Because Europe is excluded from every bulk/looped fetch (the daily refresh, and the "Growth by Period" selector), its dashboard coverage only grows when a user looks up an individual EU symbol in "Historical Trend" — that lookup persists to the DB so coverage accumulates over time. Don't shorten the auto-refresh interval or add an unbatched loop across all tracked EU symbols without checking this table first.

## Architecture and file ownership

Single package at `src/live_market_analysis/`. This project has Claude Code subagents defined in `.claude/agents/` with per-module ownership, but **do not delegate code edits to them** — write and edit code directly. Only use the subagents (e.g. `tester`, or agents invoked via the `run` skill) for actually running/building the dashboard, not for changing code.

- `apis/eodhd.py`, `apis/twelve_data.py`, `apis/itick.py` — one module per provider (`eu-api-agent`, `us-api-agent`, `asia-api-agent`)
- `fetch_raw.py` — fetches historical bars from all 3 providers, writes `data/raw/*.json` (`api-info-manager`). Public API: `fetch_bulk_historical(twelve_data_symbols, itick_pairs, period="d")` (US + Asia only, daily) and `fetch_symbol_historical(provider, *args, period="d")` (any one provider/symbol, on demand). Both merge into the existing raw JSON rather than overwriting it.
- `data_handling/merge.py`, `clean.py`, `symbols.py`, `analyze.py` — merge/clean/scrape/analyze pipeline (`data-handler`)
- `data_handling/db.py` — SQLite storage (`db-builder`)
- `news.py` — yfinance news (`news-agent`)
- `dashboard/app.py` — Dash/Plotly UI (`dashboard-builder`)

Data flow contract: `fetch_raw.py` writes `data/raw/*.json` as `{"<symbol>": [bar, ...]}` (`{"<region>:<code>": {"data": [bar, ...]}}` for iTick) → `merge.py` reads it and normalizes into one schema (`region, symbol, timestamp, open, high, low, close, volume, change, change_pct`), with `change`/`change_pct` computed bar-over-bar per symbol (first bar in a series is `NaN`) → `merge.py` never calls the API modules directly. Each symbol now contributes many historical rows over time rather than one live-quote row, so "current standing" views (top gainers/volume/volatility, region growth) should filter down with `analyze.latest_per_symbol(df)` first.

- `.cache/` (gitignored) caches API responses and Wikipedia scrapes so repeated dev runs don't re-hit live APIs.
- `market_data.db` (SQLite, gitignored) accumulates quotes, keyed on `(region, symbol, timestamp)` — safe to re-run without duplicates.

## Repo etiquette

- Commit messages: short, imperative, conventional-commit-style prefix when it fits (`fix:`, `feat:`, `refactor:`, etc.).
- No GitHub remote is configured yet; once one exists, use feature branches off `main` rather than committing directly to `main` for anything non-trivial.
