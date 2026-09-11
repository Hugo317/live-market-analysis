import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from live_market_analysis.apis import eodhd, itick, twelve_data, yahoo

RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw"


def _load(provider: str) -> dict:
    path = RAW_DIR / f"{provider}.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}
    # Guards against stale files written in the pre-historical-only flat-list
    # shape -- the new contract is always {"<symbol>": [bar, ...]}, so anything
    # else on disk is from an incompatible schema and gets discarded rather
    # than crashing the merge below.
    return data if isinstance(data, dict) else {}


def _merge_save(provider: str, updates: dict) -> None:
    """Reads the existing raw JSON for `provider`, overwrites only the keys in
    `updates`, and writes the merged result back. Never wipes unrelated entries."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    existing = _load(provider)
    existing.update(updates)
    (RAW_DIR / f"{provider}.json").write_text(json.dumps(existing))


def fetch_bulk_historical(
    twelve_data_symbols: list[str],
    itick_pairs: list[tuple[str, str]],
    period: str = "d",
) -> None:
    """Concurrently fetches historical bars for every US symbol and every Asia
    pair, merging results into data/raw/twelve_data.json and data/raw/itick.json.

    Deliberately excludes EODHD/Europe: EODHD's get_historical is unbatched (1
    call per symbol) with only 20 calls/day total, so bulk-fetching the ~20
    tracked EU symbols here would exhaust the whole day's budget in one call.
    Europe must go through fetch_symbol_historical, one symbol at a time, on
    demand.
    """
    with ThreadPoolExecutor(max_workers=2) as executor:
        td_future = executor.submit(
            lambda: {
                symbol: twelve_data.get_historical(symbol, period=period)
                for symbol in twelve_data_symbols
            }
        )
        itick_future = executor.submit(
            lambda: {
                f"{region}:{code}": itick.get_historical(region, code, period=period)
                for region, code in itick_pairs
            }
        )
        td_updates = td_future.result()
        itick_updates = itick_future.result()

    _merge_save("twelve_data", td_updates)
    _merge_save("itick", itick_updates)


def backfill_all(
    eodhd_symbols: list[str],
    twelve_data_symbols: list[str],
    itick_pairs: list[tuple[str, str]],
    from_date: str = "1990-01-01",
    itick_limit: int = 1000,
) -> dict:
    """One-shot maximum-range historical backfill across all 3 providers, for
    growing the local DB as large as the free tiers allow in a single run.

    Deliberately NOT wired to any dashboard UI action -- this makes ~60 real API
    calls (one per tracked symbol) and must only be run when explicitly invoked
    (e.g. `uv run python scripts/backfill_db.py`), never automatically. With 20
    symbols tracked per region, this uses EODHD's entire 20-calls/day budget in
    one run -- if it fails partway through EODHD, re-running the next UTC day
    picks up where it left off (each symbol is merge-saved immediately, and
    EODHD's own daily counter in `.cache/eodhd_daily_calls.json` prevents
    over-budget calls rather than silently failing).

    Twelve Data (`from_date`) and EODHD (`from_date`) both request the widest
    possible date range and let the provider truncate to what it actually has.
    iTick has no date-range param, only `limit` (bar count) -- `itick_limit`
    requests as many bars as the endpoint allows and falls back to smaller
    values if the provider rejects it.

    Returns a summary dict: {"eodhd": {...}, "twelve_data": {...}, "itick": {...}}
    each mapping symbol -> "ok" | error string, so a partial run's failures are
    visible without needing to read logs.
    """
    results: dict[str, dict[str, str]] = {"eodhd": {}, "twelve_data": {}, "itick": {}}

    for symbol in eodhd_symbols:
        try:
            bars = eodhd.get_historical(symbol, period="d", from_date=from_date)
            _merge_save("eodhd", {symbol: bars})
            results["eodhd"][symbol] = f"ok ({len(bars)} bars)"
        except Exception as e:
            results["eodhd"][symbol] = f"error: {e}"

    for symbol in twelve_data_symbols:
        try:
            bars = twelve_data.get_historical(symbol, period="d", from_date=from_date)
            _merge_save("twelve_data", {symbol: bars})
            results["twelve_data"][symbol] = f"ok ({len(bars)} bars)"
        except Exception as e:
            results["twelve_data"][symbol] = f"error: {e}"

    for region, code in itick_pairs:
        key = f"{region}:{code}"
        limit = itick_limit
        while True:
            try:
                response = itick.get_historical(region, code, period="d", limit=limit)
                _merge_save("itick", {key: response})
                bar_count = len(response.get("data", [])) if isinstance(response, dict) else 0
                results["itick"][key] = f"ok ({bar_count} bars, limit={limit})"
                break
            except Exception as e:
                if limit > 30:
                    limit = max(30, limit // 4)
                    continue
                results["itick"][key] = f"error: {e}"
                break

    return results


def backfill_yahoo(
    eodhd_symbols: list[str],
    us_symbols: list[str],
    asia_pairs: list[tuple[str, str]],
    period: str = "max",
) -> dict[str, str]:
    """Supplementary deep-history backfill via Yahoo Finance (yfinance) --
    unofficial endpoint, no API key, no documented quota, and dramatically
    deeper history than EODHD/iTick's free tiers allow (years/decades vs
    ~1yr/~440 bars). NOT a replacement for the 3 quota-tracked providers --
    run this alongside/after backfill_all. Writes data/raw/yahoo.json keyed
    "<REGION>:<symbol>" (the DB's own region/symbol convention) so merge.py
    can normalize it directly; overlapping dates get overwritten with
    Yahoo's numbers on the next merge+upsert (INSERT OR REPLACE on
    (region, symbol, timestamp)), which is fine since this is about filling
    in the deeper history these dates wouldn't otherwise have.

    Returns {"<REGION>:<symbol>": "ok (N bars)" | "error: ..."}.
    """
    results: dict[str, str] = {}
    updates: dict[str, list[dict]] = {}

    for symbol in eodhd_symbols:
        key = f"EU:{symbol}"
        try:
            bars = yahoo.get_historical(yahoo.to_eu_ticker(symbol), period=period)
            updates[key] = bars
            results[key] = f"ok ({len(bars)} bars)"
        except Exception as e:
            results[key] = f"error: {e}"

    for symbol in us_symbols:
        key = f"US:{symbol}"
        try:
            bars = yahoo.get_historical(symbol, period=period)
            updates[key] = bars
            results[key] = f"ok ({len(bars)} bars)"
        except Exception as e:
            results[key] = f"error: {e}"

    for region, code in asia_pairs:
        key = f"ASIA:{code}"
        try:
            bars = yahoo.get_historical(yahoo.to_asia_ticker(code), period=period)
            updates[key] = bars
            results[key] = f"ok ({len(bars)} bars)"
        except Exception as e:
            results[key] = f"error: {e}"

    _merge_save("yahoo", updates)
    return results


# (period, interval) combos for backfill_yahoo_deep, respecting yfinance's own
# intraday lookback limits: 1m up to ~7d, 5m up to ~60d, 1h up to ~2y; the
# daily/weekly/monthly rows support the full available history ("max").
YAHOO_DEEP_INTERVALS: list[tuple[str, str]] = [
    ("max", "1d"),
    ("max", "1wk"),
    ("max", "1mo"),
    ("2y", "1h"),
    ("60d", "5m"),
    ("7d", "1m"),
]


def backfill_yahoo_deep(
    eodhd_symbols: list[str],
    us_symbols: list[str],
    asia_pairs: list[tuple[str, str]],
    intervals: list[tuple[str, str]] = YAHOO_DEEP_INTERVALS,
    on_progress=None,
) -> dict[str, str]:
    """Multi-granularity Yahoo Finance backfill -- on top of backfill_yahoo's
    daily "max" pull, also fetches weekly/monthly (full history) and
    hourly/5-minute/1-minute (recent windows only, per yfinance's own limits)
    for every tracked symbol. This is the biggest lever for growing the DB
    since Yahoo has no documented quota, unlike the 3 tracked providers.

    Each non-daily granularity is written under a suffixed key
    ("<REGION>:<symbol>#<interval>") rather than merged into the plain
    "<REGION>:<symbol>" key, so a weekly/monthly bar never overwrites a daily
    bar that happens to land on the same calendar date in data/raw/yahoo.json.
    merge.py's normalizer strips the "#<interval>" suffix back off, so all of
    these still land in the DB as normal rows for that (region, symbol) --
    intraday bars get distinct time-of-day timestamps so they're purely
    additive; a rare weekly/monthly bar landing on the exact same daily
    timestamp will overwrite that one row on upsert, which is an acceptable
    trade-off for maximizing coverage.

    `on_progress`, if given, is called as `on_progress(done, total, combo_key)`
    after every symbol x interval combo attempted -- lets a caller render a
    live progress bar instead of waiting for the whole thing to finish.

    Returns {"<key>": "ok (N bars)" | "error: ..."} for every symbol x interval
    combo attempted.
    """
    results: dict[str, str] = {}
    updates: dict[str, list[dict]] = {}
    total = (len(eodhd_symbols) + len(us_symbols) + len(asia_pairs)) * len(intervals)
    done = 0

    def _run(base_key: str, ticker: str) -> None:
        nonlocal done
        for period, interval in intervals:
            combo_key = base_key if (period, interval) == ("max", "1d") else f"{base_key}#{interval}"
            try:
                bars = yahoo.get_historical(ticker, period=period, interval=interval)
                updates[combo_key] = bars
                results[combo_key] = f"ok ({len(bars)} bars)"
            except Exception as e:
                results[combo_key] = f"error: {e}"
            done += 1
            if on_progress:
                on_progress(done, total, combo_key)

    for symbol in eodhd_symbols:
        _run(f"EU:{symbol}", yahoo.to_eu_ticker(symbol))
    for symbol in us_symbols:
        _run(f"US:{symbol}", symbol)
    for region, code in asia_pairs:
        _run(f"ASIA:{code}", yahoo.to_asia_ticker(code))

    _merge_save("yahoo", updates)
    return results


def backfill_extra_periods(
    twelve_data_symbols: list[str],
    itick_pairs: list[tuple[str, str]],
    periods: tuple[str, ...] = ("w", "m"),
    itick_limit: int = 1000,
    on_progress=None,
) -> dict[str, str]:
    """Additional weekly/monthly bars for Twelve Data (US) + iTick (Asia),
    using quota that's typically still free after backfill_all's single daily
    pull per symbol (Twelve Data: 800/day, ~20 used by backfill_all; iTick:
    per-minute limit only, no confirmed daily cap). EODHD/Europe is
    deliberately excluded -- its free tier caps out around 1yr of history
    regardless of period, and backfill_all already spends its entire
    20-calls/day budget in one run.

    Written to separate provider files (twelve_data_extra.json,
    itick_extra.json) rather than merged into the primary daily raw files, so
    this never collides with/overwrites the primary daily pull. merge.py
    reads them optionally, the same way it reads yahoo.json.

    `on_progress`, if given, is called as `on_progress(done, total, key)` after
    every symbol x period combo attempted.

    Returns {"twelve_data:<symbol>#<period>" | "itick:<region>:<code>#<period>": "ok (N bars)" | "error: ..."}.
    """
    results: dict[str, str] = {}
    td_updates: dict[str, list[dict]] = {}
    itick_updates: dict[str, dict] = {}
    total = (len(twelve_data_symbols) + len(itick_pairs)) * len(periods)
    done = 0

    for symbol in twelve_data_symbols:
        for period in periods:
            key = f"{symbol}#{period}"
            try:
                bars = twelve_data.get_historical(symbol, period=period)
                td_updates[key] = bars
                results[f"twelve_data:{key}"] = f"ok ({len(bars)} bars)"
            except Exception as e:
                results[f"twelve_data:{key}"] = f"error: {e}"
            done += 1
            if on_progress:
                on_progress(done, total, f"twelve_data:{key}")

    for region, code in itick_pairs:
        for period in periods:
            key = f"{region}:{code}#{period}"
            limit = itick_limit
            while True:
                try:
                    response = itick.get_historical(region, code, period=period, limit=limit)
                    itick_updates[key] = response
                    bar_count = len(response.get("data", [])) if isinstance(response, dict) else 0
                    results[f"itick:{key}"] = f"ok ({bar_count} bars, limit={limit})"
                    break
                except Exception as e:
                    if limit > 30:
                        limit = max(30, limit // 4)
                        continue
                    results[f"itick:{key}"] = f"error: {e}"
                    break
            done += 1
            if on_progress:
                on_progress(done, total, f"itick:{key}")

    _merge_save("twelve_data_extra", td_updates)
    _merge_save("itick_extra", itick_updates)
    return results


def fetch_symbol_historical(provider: str, *args, period: str = "d") -> None:
    """Single-symbol on-demand fetch + persist for any of the 3 providers.

    `provider` is "eodhd" (args: symbol), "twelve_data" (args: symbol), or
    "itick" (args: region, code) -- mirrors analyze.get_symbol_history's
    calling convention. Not called from the dashboard (which is DB-read-only,
    no live calls) -- this is for ad-hoc/manual single-symbol fetches, e.g.
    from a script or a REPL.
    """
    if provider == "eodhd":
        (symbol,) = args
        bars = eodhd.get_historical(symbol, period=period)
        _merge_save("eodhd", {symbol: bars})
    elif provider == "twelve_data":
        (symbol,) = args
        bars = twelve_data.get_historical(symbol, period=period)
        _merge_save("twelve_data", {symbol: bars})
    elif provider == "itick":
        region, code = args
        response = itick.get_historical(region, code, period=period)
        _merge_save("itick", {f"{region}:{code}": response})
    else:
        raise ValueError(f"Unknown provider: {provider!r}")


if __name__ == "__main__":
    # Demo only -- do not run this module directly, it makes real API calls.
    fetch_bulk_historical(
        twelve_data_symbols=["AAPL"],
        itick_pairs=[("HK", "700")],
    )
    fetch_symbol_historical("eodhd", "VOD.LSE")
    print(f"Raw historical data written to {RAW_DIR}")
