import yfinance as yf

from live_market_analysis.data_handling.cache import cached_get


def to_eu_ticker(eodhd_symbol: str) -> str:
    """'III.LSE' -> 'III.L' (Yahoo's London Stock Exchange suffix)."""
    return f"{eodhd_symbol.removesuffix('.LSE')}.L"


def to_asia_ticker(code: str) -> str:
    """'700' -> '0700.HK' (Yahoo zero-pads Hong Kong codes to 4 digits)."""
    return f"{code.zfill(4)}.HK"


def _fetch(ticker: str, period: str, interval: str) -> list[dict]:
    hist = yf.Ticker(ticker).history(period=period, interval=interval)
    if hist.empty:
        return []
    return [
        {
            # Full timestamp (not just date) so intraday bars (1h/5m/1m) get
            # distinct keys instead of colliding on a shared date string.
            "date": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "open": float(row["Open"]),
            "high": float(row["High"]),
            "low": float(row["Low"]),
            "close": float(row["Close"]),
            "volume": float(row["Volume"]),
        }
        for ts, row in hist.iterrows()
    ]


def get_historical(ticker: str, period: str = "max", interval: str = "1d") -> list[dict]:
    """Bars, oldest -> newest, for a Yahoo-format ticker (e.g. 'AAPL', 'VOD.L',
    '0700.HK'). Unofficial endpoint (no API key, no documented quota) --
    much deeper history than EODHD/iTick's free tiers allow, but no
    uptime/rate-limit guarantee. Supplementary source, not a replacement for
    the 3 quota-tracked providers -- see CLAUDE.md.

    `interval` follows yfinance's own limits: intraday granularities are only
    available for a recent window regardless of `period` -- 1m up to ~7d, up
    to 5m/15m/30m/90m up to ~60d, 60m/1h up to ~2y; 1d/5d/1wk/1mo/3mo support
    the full available history ("max").
    """
    return cached_get(
        "yahoo", "history", {"ticker": ticker, "period": period, "interval": interval}, lambda: _fetch(ticker, period, interval)
    )
