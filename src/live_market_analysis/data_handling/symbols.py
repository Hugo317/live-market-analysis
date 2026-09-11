from io import StringIO

import pandas as pd
import requests

from live_market_analysis.data_handling.cache import cached_get

SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
FTSE100_URL = "https://en.wikipedia.org/wiki/FTSE_100_Index"
FTSE250_URL = "https://en.wikipedia.org/wiki/FTSE_250_Index"
HSI_URL = "https://en.wikipedia.org/wiki/Hang_Seng_Index"

HEADERS = {"User-Agent": "Mozilla/5.0 (live-market-analysis research script)"}

# Hang Seng Index (the only Hong Kong constituent list Wikipedia has as a
# clean, scrapeable table -- Hang Seng Composite/TECH indices and a general
# HKEX-listed-companies page don't have usable tables) tops out at ~85
# constituents, well short of 200. US (S&P 500, 503 members) and Europe
# (FTSE 100 + FTSE 250 combined, ~350 members) both comfortably support 200.
ASIA_MAX = 85


def _fetch_tables(url: str, match: str) -> list:
    html = requests.get(url, headers=HEADERS).text
    return pd.read_html(StringIO(html), match=match)


def _dedupe(items: list[str]) -> list[str]:
    seen = set()
    out = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def get_us_symbols(n: int = 200) -> list[str]:
    def fetch() -> list[str]:
        df = _fetch_tables(SP500_URL, match="Symbol")[0]
        return df["Symbol"].tolist()

    symbols = cached_get("wikipedia", "sp500", {}, fetch)
    symbols = [s.replace(".", "-") for s in symbols]  # e.g. BRK.B -> BRK-B
    return symbols[:n]


def get_europe_symbols(n: int = 200) -> list[str]:
    """Returns EODHD-ready tickers, e.g. 'III.LSE'. FTSE 100 (large-cap, ~100
    members) constituents come first, topped up with FTSE 250 (mid-cap, ~250
    members) to reach `n` -- combined that's ~350 available, well past 200."""

    def fetch_100() -> list[str]:
        df = _fetch_tables(FTSE100_URL, match="Ticker")[0]
        return df["Ticker"].dropna().astype(str).tolist()

    def fetch_250() -> list[str]:
        df = _fetch_tables(FTSE250_URL, match="Ticker")[0]
        return df["Ticker"].dropna().astype(str).tolist()

    ftse100 = cached_get("wikipedia", "ftse100", {}, fetch_100)
    ftse250 = cached_get("wikipedia", "ftse250", {}, fetch_250)
    tickers = _dedupe(ftse100 + ftse250)
    tickers = [t.replace(".", "-") for t in tickers]  # e.g. BT.A -> BT-A (EODHD can't parse an embedded dot before .LSE)
    return [f"{t}.LSE" for t in tickers[:n]]


def get_asia_pairs(n: int = ASIA_MAX) -> list[tuple[str, str]]:
    """Returns iTick-ready (region, code) pairs, e.g. ('HK', '700') (Hang Seng
    constituents). Capped at ~85 -- see ASIA_MAX."""

    def fetch() -> list[str]:
        df = _fetch_tables(HSI_URL, match="Sub-index")[0]
        return df["Ticker"].tolist()

    tickers = cached_get("wikipedia", "hsi", {}, fetch)
    codes = [t.split(":")[-1].strip() for t in tickers]
    return [("HK", code) for code in codes[: min(n, ASIA_MAX)]]


def get_us_symbol_names(n: int = 200) -> dict[str, str]:
    """Maps get_us_symbols()-style tickers -> company name, e.g. 'AAPL' -> 'Apple Inc.'"""

    def fetch() -> list[list[str]]:
        df = _fetch_tables(SP500_URL, match="Symbol")[0]
        return df[["Symbol", "Security"]].values.tolist()

    rows = cached_get("wikipedia", "sp500_names", {}, fetch)
    return {symbol.replace(".", "-"): name for symbol, name in rows[:n]}


def get_europe_symbol_names(n: int = 200) -> dict[str, str]:
    """Maps get_europe_symbols()-style tickers -> company name, e.g. 'III.LSE' -> '3i'"""

    def fetch_100() -> list[list[str]]:
        df = _fetch_tables(FTSE100_URL, match="Ticker")[0][["Ticker", "Company"]].dropna()
        return df.astype(str).values.tolist()

    def fetch_250() -> list[list[str]]:
        df = _fetch_tables(FTSE250_URL, match="Ticker")[0][["Ticker", "Company"]].dropna()
        return df.astype(str).values.tolist()

    rows_100 = cached_get("wikipedia", "ftse100_names", {}, fetch_100)
    rows_250 = cached_get("wikipedia", "ftse250_names", {}, fetch_250)

    names: dict[str, str] = {}
    for ticker, name in rows_100 + rows_250:
        key = f"{ticker.replace('.', '-')}.LSE"
        names.setdefault(key, name)  # first occurrence wins (FTSE 100 takes priority over 250)
    return dict(list(names.items())[:n])


def get_asia_symbol_names(n: int = ASIA_MAX) -> dict[str, str]:
    """Maps get_asia_pairs()-style codes -> company name, e.g. '700' -> 'Tencent'"""

    def fetch() -> list[list[str]]:
        df = _fetch_tables(HSI_URL, match="Sub-index")[0]
        return df[["Ticker", "Name"]].values.tolist()

    rows = cached_get("wikipedia", "hsi_names", {}, fetch)
    return {ticker.split(":")[-1].strip(): name for ticker, name in rows[: min(n, ASIA_MAX)]}


if __name__ == "__main__":
    print("US:", get_us_symbols())
    print("Europe:", get_europe_symbols())
    print("Asia:", get_asia_pairs())
