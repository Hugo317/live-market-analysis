from io import StringIO

import pandas as pd
import requests

from live_market_analysis.data_handling.cache import cached_get

SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
FTSE100_URL = "https://en.wikipedia.org/wiki/FTSE_100_Index"
HSI_URL = "https://en.wikipedia.org/wiki/Hang_Seng_Index"

HEADERS = {"User-Agent": "Mozilla/5.0 (live-market-analysis research script)"}


def _fetch_tables(url: str, match: str) -> list:
    html = requests.get(url, headers=HEADERS).text
    return pd.read_html(StringIO(html), match=match)


def get_us_symbols(n: int = 20) -> list[str]:
    def fetch() -> list[str]:
        df = _fetch_tables(SP500_URL, match="Symbol")[0]
        return df["Symbol"].tolist()

    symbols = cached_get("wikipedia", "sp500", {}, fetch)
    symbols = [s.replace(".", "-") for s in symbols]  # e.g. BRK.B -> BRK-B
    return symbols[:n]


def get_europe_symbols(n: int = 20) -> list[str]:
    """Returns EODHD-ready tickers, e.g. 'III.LSE' (FTSE 100 constituents)."""

    def fetch() -> list[str]:
        df = _fetch_tables(FTSE100_URL, match="Ticker")[0]
        return df["Ticker"].tolist()

    tickers = cached_get("wikipedia", "ftse100", {}, fetch)
    tickers = [t.replace(".", "-") for t in tickers]  # e.g. BT.A -> BT-A (EODHD can't parse an embedded dot before .LSE)
    return [f"{t}.LSE" for t in tickers[:n]]


def get_asia_pairs(n: int = 20) -> list[tuple[str, str]]:
    """Returns iTick-ready (region, code) pairs, e.g. ('HK', '700') (Hang Seng constituents)."""

    def fetch() -> list[str]:
        df = _fetch_tables(HSI_URL, match="Sub-index")[0]
        return df["Ticker"].tolist()

    tickers = cached_get("wikipedia", "hsi", {}, fetch)
    codes = [t.split(":")[-1].strip() for t in tickers]
    return [("HK", code) for code in codes[:n]]


def get_us_symbol_names(n: int = 20) -> dict[str, str]:
    """Maps get_us_symbols()-style tickers -> company name, e.g. 'AAPL' -> 'Apple Inc.'"""

    def fetch() -> list[list[str]]:
        df = _fetch_tables(SP500_URL, match="Symbol")[0]
        return df[["Symbol", "Security"]].values.tolist()

    rows = cached_get("wikipedia", "sp500_names", {}, fetch)
    return {symbol.replace(".", "-"): name for symbol, name in rows[:n]}


def get_europe_symbol_names(n: int = 20) -> dict[str, str]:
    """Maps get_europe_symbols()-style tickers -> company name, e.g. 'III.LSE' -> '3i'"""

    def fetch() -> list[list[str]]:
        df = _fetch_tables(FTSE100_URL, match="Ticker")[0]
        return df[["Ticker", "Company"]].values.tolist()

    rows = cached_get("wikipedia", "ftse100_names", {}, fetch)
    return {f"{ticker.replace('.', '-')}.LSE": name for ticker, name in rows[:n]}


def get_asia_symbol_names(n: int = 20) -> dict[str, str]:
    """Maps get_asia_pairs()-style codes -> company name, e.g. '700' -> 'Tencent'"""

    def fetch() -> list[list[str]]:
        df = _fetch_tables(HSI_URL, match="Sub-index")[0]
        return df[["Ticker", "Name"]].values.tolist()

    rows = cached_get("wikipedia", "hsi_names", {}, fetch)
    return {ticker.split(":")[-1].strip(): name for ticker, name in rows[:n]}


if __name__ == "__main__":
    print("US:", get_us_symbols())
    print("Europe:", get_europe_symbols())
    print("Asia:", get_asia_pairs())
