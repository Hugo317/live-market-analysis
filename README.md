# Live Market Analysis

A Dash dashboard tracking stock market data across Europe, the US, and Asia, with growth analysis and region performance.

> **The data is static.** The free API tiers this project uses are tightly rate-limited (for example, 20 calls a day for European quotes), so a public dashboard can't pull live data. The hosted demo reads a stored snapshot instead: daily bars for 485 symbols from 11 Sep 2024 to 11 Sep 2026. Nothing is fetched live, and the news panels are switched off in the demo. The snapshot is `data/snapshot.db`, built from the full local database by `scripts/build_snapshot.py`.

## Run the static demo locally

No API keys needed. With only the committed snapshot in `data/`:

```
uv sync
uv run python -m live_market_analysis.dashboard.app
```

If a full `market_data.db` exists in the repo root, the app uses that instead of the snapshot.

## Setup (to fetch fresh data)

1. Install dependencies:
   ```
   uv sync
   ```

2. Copy `.env.example` to `.env` and fill in your API keys:
   ```
   cp .env.example .env
   ```
   You'll need free-tier accounts with:
   - [EODHD](https://eodhd.com/) — Europe quotes/history (`EODHD_API_KEY`)
   - [Twelve Data](https://twelvedata.com/) — US quotes/history (`TWELVE_DATA_API_KEY`)
   - [iTick](https://itick.org/) — Asia quotes/history (`I_TICK_API_KEY`). Use the **free-tier endpoint** `api-free.itick.org` (the base URL is already set correctly in `apis/itick.py`) — `api.itick.org` rejects free-tier keys.

   Leave `EODHD_IS_PREMIUM=false` unless you've upgraded that plan.

## Running the dashboard

```
uv run python -m live_market_analysis.dashboard.app
```

Then open http://127.0.0.1:8050.

**This app is designed to be checked once a day, not left open continuously.** See "API quota limits" below for why. Use the "Refresh now" button whenever you want current data; a 24-hour auto-refresh runs as a safety net if the tab is left open.

To enable Flask's debug/reload mode for local development:
```
DASHBOARD_DEBUG=true uv run python -m live_market_analysis.dashboard.app
```

## API quota limits (important)

Each provider's free tier has different limits, and the app is built around them — don't shorten the auto-refresh interval or loosely loop calls across all tracked symbols without checking this table first:

| Provider | Free tier limit | Notes |
|---|---|---|
| EODHD (Europe) | **20 calls/day total** | Not per-minute. Enforced locally in `apis/eodhd.py` via a daily counter (`.cache/eodhd_daily_calls.json`) that raises before exceeding it. `get_quotes()` batches all symbols into 1 call; `get_historical()`/`get_intraday()` do not batch. |
| Twelve Data (US) | 800 calls/day, 8 calls/min | No batch quote endpoint — `get_quotes()` loops one call per symbol (20 calls per full US refresh). |
| iTick (Asia) | 5 calls/min | No confirmed daily cap. `get_quotes()` loops one call per symbol; enforced via a sliding-window rate limiter (`data_handling/rate_limiter.py`). |
| yfinance (news) | None (free, unauthenticated) | Used for company news and the "Top Stories" feed — no special handling needed. |

The dashboard's "Growth by Period" selector (hourly/daily/weekly/monthly) deliberately **excludes Europe** — since `get_historical()` isn't batched, looping the full 20-symbol EU list would exhaust the entire daily EODHD budget in a single interaction.

## Project structure

```
src/live_market_analysis/
├── apis/                  # One module per data provider (owned by eu-api-agent, us-api-agent, asia-api-agent)
│   ├── eodhd.py
│   ├── twelve_data.py
│   └── itick.py
├── fetch_raw.py           # Concurrently fetches all 3 providers, writes data/raw/*.json (api-info-manager)
├── data_handling/
│   ├── merge.py           # Reads data/raw/*.json, normalizes into one schema (data-handler)
│   ├── clean.py           # Dedupe/coerce types/sort (data-handler)
│   ├── symbols.py         # Scrapes Wikipedia for S&P 500 / FTSE 100 / Hang Seng symbol lists (data-handler)
│   ├── analyze.py         # Growth calculations, top gainers/losers, region performance (data-handler)
│   ├── db.py               # SQLite storage (db-builder)
│   ├── cache.py            # Generic disk cache for all API/scrape calls
│   └── rate_limiter.py     # Sliding-window rate limiter
├── news.py                 # yfinance company news + top-stories feed (news-agent)
└── dashboard/
    └── app.py               # Dash/Plotly UI (dashboard-builder)
```

This project uses [Claude Code subagents](https://docs.claude.com/en/docs/claude-code) (`.claude/agents/`) with clear file ownership — see `orchestrator.md` for the full breakdown of who owns what.

## Development notes

- API responses and Wikipedia scrapes are cached to `.cache/` (gitignored) — repeated dev runs reuse cached data instead of re-hitting live APIs.
- `market_data.db` (SQLite, gitignored) accumulates quotes over time, keyed on `(region, symbol, timestamp)` — safe to re-run without creating duplicates.
- `data/raw/*.json` (gitignored) is the handoff point between fetching (`fetch_raw.py`) and merging (`merge.py`) — `merge.py` never calls the API modules directly.
