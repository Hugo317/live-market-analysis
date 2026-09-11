from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from live_market_analysis.apis import eodhd, itick, twelve_data


def _growth_pct(closes: list[float]) -> float | None:
    """Growth from the second-to-last bar's close to the last bar's close."""
    last_two = closes[-2:]
    if len(last_two) < 2:
        return None
    previous, latest = last_two
    return (latest - previous) / previous * 100


def eodhd_growth(symbol: str, period: str = "d") -> float | None:
    bars = eodhd.get_historical(symbol, period=period)  # already oldest -> newest
    return _growth_pct([b["close"] for b in bars])


def twelve_data_growth(symbol: str, period: str = "d") -> float | None:
    bars = twelve_data.get_historical(symbol, period=period)  # newest -> oldest
    closes = [float(b["close"]) for b in reversed(bars)]
    return _growth_pct(closes)


def itick_growth(region: str, code: str, period: str = "d") -> float | None:
    response = itick.get_historical(region, code, period=period)  # oldest -> newest
    return _growth_pct([b["c"] for b in response["data"]])


def get_symbol_history(provider: str, *args, period: str = "d") -> tuple[list, list]:
    """Returns (timestamps, closes) for a single symbol, oldest -> newest, for a
    trend-line chart. `provider` is "eodhd" (args: symbol), "twelve_data" (args:
    symbol), or "itick" (args: region, code)."""
    if provider == "eodhd":
        (symbol,) = args
        bars = eodhd.get_historical(symbol, period=period)  # already oldest -> newest
        return [b["date"] for b in bars], [b["close"] for b in bars]
    elif provider == "twelve_data":
        (symbol,) = args
        bars = list(reversed(twelve_data.get_historical(symbol, period=period)))  # newest -> oldest, so reverse
        return [b["datetime"] for b in bars], [float(b["close"]) for b in bars]
    elif provider == "itick":
        region, code = args
        response = itick.get_historical(region, code, period=period)  # already oldest -> newest
        bars = response["data"]
        return [b["t"] for b in bars], [b["c"] for b in bars]
    else:
        raise ValueError(f"Unknown provider: {provider!r}")


def latest_per_symbol(df: pd.DataFrame) -> pd.DataFrame:
    """Collapses a multi-timestamp historical DataFrame (many bars per
    region+symbol) down to the single most-recent bar per region+symbol.

    Needed now that `merge_quotes()` returns full historical series rather than
    one current-quote row per symbol: `top_gainers`/`top_losers`/`top_by_volume`/
    `with_volatility`/`top_volatility` all rank whatever rows they're given, so
    calling them directly on the full historical DataFrame would rank individual
    historical bars instead of each symbol's current standing. Callers building a
    "top gainers today" style view should call this first, e.g.
    `top_gainers(latest_per_symbol(df))`.
    """
    return (
        df.sort_values("timestamp")
        .groupby(["region", "symbol"], as_index=False)
        .tail(1)
        .reset_index(drop=True)
    )


def top_gainers(df: pd.DataFrame, n: int = 5) -> pd.DataFrame:
    return df.nlargest(n, "change_pct")


def top_losers(df: pd.DataFrame, n: int = 5) -> pd.DataFrame:
    return df.nsmallest(n, "change_pct")


def region_growth(df: pd.DataFrame) -> pd.DataFrame:
    """Average change_pct per region, sorted descending (proxy for "growing
    countries" since we track regions, not individual countries)."""
    return (
        df.groupby("region")["change_pct"]
        .mean()
        .reset_index()
        .sort_values("change_pct", ascending=False)
        .reset_index(drop=True)
    )


def top_by_volume(df: pd.DataFrame, n: int = 10) -> pd.DataFrame:
    return df.nlargest(n, "volume")


def with_volatility(df: pd.DataFrame) -> pd.DataFrame:
    """Adds a `range_pct` column: (high - low) / close * 100, a simple
    intraday-volatility proxy from data we already have (no extra API calls)."""
    df = df.copy()
    df["range_pct"] = (df["high"] - df["low"]) / df["close"] * 100
    return df


def top_volatility(df: pd.DataFrame, n: int = 10) -> pd.DataFrame:
    return with_volatility(df).nlargest(n, "range_pct")


def _twelve_data_period_rows(symbols: list[str], period: str) -> list[dict]:
    rows = []
    for symbol in symbols:
        try:
            rows.append({"region": "US", "symbol": symbol, "growth_pct": twelve_data_growth(symbol, period=period), "error": None})
        except Exception as e:
            rows.append({"region": "US", "symbol": symbol, "growth_pct": None, "error": str(e)})
    return rows


def _itick_period_rows(pairs: list[tuple[str, str]], period: str) -> list[dict]:
    rows = []
    for region, code in pairs:
        try:
            rows.append({"region": "ASIA", "symbol": code, "growth_pct": itick_growth(region, code, period=period), "error": None})
        except Exception as e:
            rows.append({"region": "ASIA", "symbol": code, "growth_pct": None, "error": str(e)})
    return rows


def period_growth_all(twelve_data_symbols: list[str], itick_pairs: list[tuple[str, str]], period: str = "d") -> pd.DataFrame:
    """Growth-by-period across all tracked US + Asia symbols, sorted descending.

    Europe/EODHD is deliberately excluded: EODHD's free plan allows only 20 API
    calls/day total, and get_historical() isn't batched, so looping all EU
    symbols here would exhaust the entire daily EODHD budget in one call. US
    (Twelve Data, 800 calls/day) and Asia (iTick, per-minute limit only) don't
    have that constraint.
    """
    with ThreadPoolExecutor(max_workers=2) as executor:
        us_future = executor.submit(_twelve_data_period_rows, twelve_data_symbols, period)
        asia_future = executor.submit(_itick_period_rows, itick_pairs, period)
        rows = us_future.result() + asia_future.result()

    df = pd.DataFrame(rows)
    return df.sort_values("growth_pct", ascending=False, na_position="last").reset_index(drop=True)


if __name__ == "__main__":
    # Demo using only local data/raw/*.json (via merge_quotes/clean) -- does not
    # call any live API. eodhd_growth/twelve_data_growth/itick_growth/
    # get_symbol_history/period_growth_all all hit live APIs and are deliberately
    # not exercised here.
    from live_market_analysis.data_handling.clean import clean
    from live_market_analysis.data_handling.merge import merge_quotes

    try:
        df = clean(merge_quotes())
    except FileNotFoundError as e:
        print(e)
    else:
        latest = latest_per_symbol(df)

        print("Top gainers (latest bar per symbol):")
        print(top_gainers(latest))

        print("\nRegion growth:")
        print(region_growth(df))
