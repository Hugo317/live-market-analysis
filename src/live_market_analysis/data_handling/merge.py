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
    # key is "REGION:CODE"; bars are already oldest -> newest
    _, code = key.split(":", 1)
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
    return pd.DataFrame(rows, columns=COLUMNS)


if __name__ == "__main__":
    try:
        print(merge_quotes())
    except FileNotFoundError as e:
        print(e)
