# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Dash dashboard tracking **historical** stock market data across Europe (EODHD), the US (Twelve Data), and Asia (iTick), plus company/market news via yfinance. **The dashboard itself makes zero live API calls** — it only ever reads `market_data.db`. All fetching happens separately via one-off scripts in `scripts/`:

- `scripts/backfill_db.py` — one-shot max-range historical backfill across all 3 quota-tracked providers (~60 calls total: 20 EU/EODHD, 20 US/Twelve Data, 20 Asia/iTick). Uses EODHD's *entire* daily budget in one run.
- `scripts/backfill_yahoo.py` — supplementary deep-history backfill via Yahoo Finance (`apis/yahoo.py`, using `yfinance`). Unofficial endpoint, no API key, no documented quota, and much deeper history than EODHD/iTick's free tiers allow (years/decades vs ~1yr/~440 bars) — fills gaps the 3 primary providers can't reach, but isn't a replacement for them (no uptime/rate-limit guarantee).

Never run either script (or otherwise call a live API) without the user's explicit confirmation first.

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
| EODHD (Europe) | **20 calls/day total**, not per-minute | Enforced via a daily counter in `.cache/eodhd_daily_calls.json` that raises before exceeding it. `get_historical()`/`get_intraday()` are not batched (1 call per symbol) and return only ~1yr of history even with `from_date` set far back — the free tier caps the range server-side. |
| Twelve Data (US) | 800 calls/day, 8 calls/min | No batch endpoint — one `get_historical()` call per symbol. Returns up to 5,000 daily bars per call (as far back as ~2006 for most symbols). |
| iTick (Asia) | 5 calls/min | No confirmed daily cap. One call per symbol; enforced via a sliding-window limiter (`data_handling/rate_limiter.py`). Must use `api-free.itick.org`, not `api.itick.org` — the latter rejects free-tier keys. Server-side caps responses to ~440 bars regardless of requested `limit`. |
| Yahoo Finance (`apis/yahoo.py`, via `yfinance`) | None documented — unofficial endpoint, no API key | Supplementary deep-history source only (`scripts/backfill_yahoo.py`), not a replacement for the 3 above. Returns years/decades of daily history (e.g. ~11.5k bars for AAPL back to 1980) where the free-tier providers cap out. No uptime/rate-limit SLA — can break without notice since it scrapes Yahoo's internal endpoints. Ticker format differs from the other providers: EU needs `apis.yahoo.to_eu_ticker()` (`III.LSE` → `III.L`), Asia needs `apis.yahoo.to_asia_ticker()` (`700` → `0700.HK`), US tickers are used as-is. |
| yfinance (news, `news.py`) | None (free, unauthenticated) | No special handling needed. |

`fetch_raw.backfill_all()`/`backfill_yahoo()` are the only paths that call EODHD, Twelve Data, or iTick with a wide date range or Yahoo at all — run only via the `scripts/` entry points above, and only with the user's explicit go-ahead each time.

## Architecture and file ownership

Single package at `src/live_market_analysis/`. This project has Claude Code subagents defined in `.claude/agents/` with per-module ownership, but **do not delegate to them** — write, edit, and verify code directly (including testing/verification passes; don't deploy the `tester` subagent for that). The only time a subagent should be used is to actually launch/run the dashboard process for the user (e.g. via the `run` skill) — never for writing, editing, or checking code.

- `apis/eodhd.py`, `apis/twelve_data.py`, `apis/itick.py` — one module per quota-tracked provider (`eu-api-agent`, `us-api-agent`, `asia-api-agent`)
- `apis/yahoo.py` — supplementary Yahoo Finance (`yfinance`) historical fetcher; not owned by a region subagent since it's cross-region and not quota-tracked
- `fetch_raw.py` — fetches historical bars from all providers, writes `data/raw/*.json` (`api-info-manager`). Public API: `fetch_bulk_historical(twelve_data_symbols, itick_pairs, period="d")` (US + Asia only, daily), `fetch_symbol_historical(provider, *args, period="d")` (any one provider/symbol, ad-hoc), `backfill_all(...)` (one-shot max-range across the 3 quota-tracked providers), `backfill_yahoo(...)` (one-shot max-range via Yahoo). All merge into the existing raw JSON rather than overwriting it.
- `scripts/backfill_db.py`, `scripts/backfill_yahoo.py` — the only call sites that should ever invoke `backfill_all`/`backfill_yahoo`; never call them from the dashboard or automatically
- `data_handling/merge.py`, `clean.py`, `symbols.py`, `analyze.py` — merge/clean/scrape/analyze pipeline (`data-handler`)
- `data_handling/db.py` — SQLite storage (`db-builder`)
- `news.py` — yfinance news (`news-agent`)
- `dashboard/app.py` — Dash/Plotly UI (`dashboard-builder`). **Read-only over the DB — no fetch/refresh calls anywhere in the app.** Global/US/Europe/Asia tabs scope every section (hero stats, gainers, volume, volatility, symbol search); Region Performance only renders on the Global tab. The one live call left in the dashboard is Top Stories (yfinance, free/unauthenticated), fetched once on page load only, never on tab clicks.

Data flow contract: `fetch_raw.py` writes `data/raw/*.json` as `{"<symbol>": [bar, ...]}` (`{"<region>:<code>": {"data": [bar, ...]}}` for iTick, `{"<REGION>:<symbol>": [bar, ...]}` for yahoo) → `merge.py` reads it and normalizes into one schema (`region, symbol, timestamp, open, high, low, close, volume, change, change_pct`), with `change`/`change_pct` computed bar-over-bar per symbol (first bar in a series is `NaN`) → `merge.py` never calls the API modules directly. `data/raw/yahoo.json` is optional — `merge_quotes()` skips it silently if it doesn't exist yet. Each symbol contributes many historical rows over time rather than one live-quote row, so "current standing" views (top gainers/volume/volatility, region growth) should filter down with `analyze.latest_per_symbol(df)` first.

- `.cache/` (gitignored) caches API responses and Wikipedia scrapes so repeated dev runs don't re-hit live APIs.
- `market_data.db` (SQLite, gitignored) accumulates quotes, keyed on `(region, symbol, timestamp)` — safe to re-run without duplicates.

## Repo etiquette

- Commit messages: short, imperative, conventional-commit-style prefix when it fits (`fix:`, `feat:`, `refactor:`, etc.).
- No GitHub remote is configured yet; once one exists, use feature branches off `main` rather than committing directly to `main` for anything non-trivial.
