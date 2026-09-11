import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from live_market_analysis.apis import eodhd, itick, twelve_data

RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw"


def _load(provider: str) -> dict:
    path = RAW_DIR / f"{provider}.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}


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


def fetch_symbol_historical(provider: str, *args, period: str = "d") -> None:
    """Single-symbol on-demand fetch + persist for any of the 3 providers.

    `provider` is "eodhd" (args: symbol), "twelve_data" (args: symbol), or
    "itick" (args: region, code) -- mirrors analyze.get_symbol_history's
    calling convention. This is the only path that should ever call EODHD's
    get_historical from the app's normal flow (e.g. a user picking a EU
    symbol in the dashboard's trend chart).
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
