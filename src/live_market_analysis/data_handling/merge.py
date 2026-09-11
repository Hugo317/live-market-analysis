import json
from pathlib import Path

import pandas as pd

RAW_DIR = Path(__file__).resolve().parents[3] / "data" / "raw"

COLUMNS = ["region", "symbol", "timestamp", "open", "high", "low", "close", "volume", "change", "change_pct"]


def _load_raw(provider: str) -> dict:
    path = RAW_DIR / f"{provider}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"No raw data found for '{provider}' at {path}. "
            "Ask the api-info-manager to run fetch_raw first to populate data/raw/."
        )
    return json.loads(path.read_text())


def _with_change(rows: list[dict]) -> list[dict]:
    """Fills in `change`/`change_pct` bar-over-bar within a single symbol's own
    (already oldest -> newest ordered) series. The first bar has no previous bar
    to compare against, so it gets None/NaN for both."""
    previous_close = None
    for row in rows:
        if previous_close is None:
            row["change"] = None
            row["change_pct"] = None
        else:
            row["change"] = row["close"] - previous_close
            row["change_pct"] = (row["close"] - previous_close) / previous_close * 100 if previous_close else None
        previous_close = row["close"]
    return rows


def _normalize_eodhd_symbol(symbol: str, bars: list[dict]) -> list[dict]:
    # bars are already oldest -> newest
    rows = [
        {
            "region": "EU",
            "symbol": symbol,
            "timestamp": pd.to_datetime(bar["date"]),
            "open": bar["open"],
            "high": bar["high"],
            "low": bar["low"],
            "close": bar["close"],
            "volume": bar["volume"],
        }
        for bar in bars
    ]
    return _with_change(rows)


def _normalize_twelve_data_symbol(symbol: str, bars: list[dict]) -> list[dict]:
    # symbol may carry a "#<period>" suffix (e.g. "AAPL#w" from
    # backfill_extra_periods) -- strip it back off before storing.
    symbol = symbol.split("#", 1)[0]
    # bars are newest -> oldest as stored; reverse to oldest -> newest before diffing
    bars = list(reversed(bars))
    rows = [
        {
            "region": "US",
            "symbol": symbol,
            "timestamp": pd.to_datetime(bar["datetime"]),
            "open": float(bar["open"]),
            "high": float(bar["high"]),
            "low": float(bar["low"]),
            "close": float(bar["close"]),
            "volume": float(bar["volume"]),
        }
        for bar in bars
    ]
    return _with_change(rows)


def _normalize_itick_key(key: str, response: dict) -> list[dict]:
    # key is "REGION:CODE", optionally with a "#<period>" suffix on the code
    # (e.g. "HK:700#w" from backfill_extra_periods); bars are already oldest -> newest
    _, code = key.split(":", 1)
    code = code.split("#", 1)[0]
    bars = response["data"]
    rows = [
        {
            "region": "ASIA",
            "symbol": code,
            "timestamp": pd.to_datetime(bar["t"], unit="ms"),
            "open": bar["o"],
            "high": bar["h"],
            "low": bar["l"],
            "close": bar["c"],
            "volume": bar["v"],
        }
        for bar in bars
    ]
    return _with_change(rows)


def _normalize_yahoo_key(key: str, bars: list[dict]) -> list[dict]:
    # key is "REGION:SYMBOL" using the DB's own region/symbol convention
    # (e.g. "EU:III.LSE", "US:AAPL", "ASIA:700"), optionally with a
    # "#<interval>" suffix on the symbol (e.g. "US:AAPL#1wk" from
    # backfill_yahoo_deep) -- strip it back off before storing. bars are
    # already oldest -> newest.
    region, symbol = key.split(":", 1)
    symbol = symbol.split("#", 1)[0]
    rows = [
        {
            "region": region,
            "symbol": symbol,
            "timestamp": pd.to_datetime(bar["date"]),
            "open": bar["open"],
            "high": bar["high"],
            "low": bar["low"],
            "close": bar["close"],
            "volume": bar["volume"],
        }
        for bar in bars
    ]
    return _with_change(rows)


def _normalize_all(provider: str, data: dict, normalize_symbol) -> list[dict]:
    """Applies `normalize_symbol` to each symbol's bar series, skipping (and
    reporting) any symbol whose data is malformed/unparseable instead of letting
    one bad entry crash the whole merge."""
    rows = []
    for key, bars in data.items():
        try:
            rows += normalize_symbol(key, bars)
        except (KeyError, ValueError, TypeError) as e:
            print(f"Skipping malformed {provider} series ({key}): {e}")
    return rows


def merge_quotes() -> pd.DataFrame:
    """Reads raw historical bars from data/raw/ (written by fetch_raw) and combines
    them into one DataFrame with a shared schema, one row per historical bar per
    symbol. Does not call any API itself."""
    rows = []
    rows += _normalize_all("eodhd", _load_raw("eodhd"), _normalize_eodhd_symbol)
    rows += _normalize_all("twelve_data", _load_raw("twelve_data"), _normalize_twelve_data_symbol)
    rows += _normalize_all("itick", _load_raw("itick"), _normalize_itick_key)
    # Yahoo, and the extra-period Twelve Data/iTick pulls, are supplementary
    # and optional -- these files only exist once the corresponding backfill
    # has been run, unlike the 3 required providers above.
    for provider, normalize_fn in (
        ("yahoo", _normalize_yahoo_key),
        ("twelve_data_extra", _normalize_twelve_data_symbol),
        ("itick_extra", _normalize_itick_key),
    ):
        try:
            rows += _normalize_all(provider, _load_raw(provider), normalize_fn)
        except FileNotFoundError:
            pass
    return pd.DataFrame(rows, columns=COLUMNS)


if __name__ == "__main__":
    try:
        print(merge_quotes())
    except FileNotFoundError as e:
        print(e)
