import os

import requests
from dotenv import load_dotenv

from live_market_analysis.data_handling.cache import cached_get
from live_market_analysis.data_handling.rate_limiter import RateLimiter

load_dotenv()

BASE_URL = "https://api.twelvedata.com"

PERIOD_TO_INTERVAL = {"d": "1day", "w": "1week", "m": "1month"}

# Free/Basic plan limit is 8 calls/minute.
_limiter = RateLimiter(calls_per_minute=8)


def _fetch(path: str, params: dict) -> dict:
    _limiter.wait()
    api_key = os.environ["TWELVE_DATA_API_KEY"]
    response = requests.get(f"{BASE_URL}/{path}", params={**params, "apikey": api_key})
    if not response.ok:
        raise requests.exceptions.HTTPError(
            f"{response.status_code} error: {response.text}", response=response
        )
    return response.json()


def _get(path: str, params: dict) -> dict:
    return cached_get("twelve_data", path, params, lambda: _fetch(path, params))


def get_quote(symbol: str, exchange: str | None = None) -> dict:
    params = {"symbol": symbol}
    if exchange:
        params["exchange"] = exchange
    return _get("quote", params)


def get_quotes(symbols: list[str]) -> list[dict]:
    return [get_quote(symbol) for symbol in symbols]


def get_historical(symbol: str, period: str = "d", from_date: str | None = None, to_date: str | None = None) -> list[dict]:
    params = {"symbol": symbol, "interval": PERIOD_TO_INTERVAL[period]}
    if from_date:
        params["start_date"] = from_date
    if to_date:
        params["end_date"] = to_date
    return _get("time_series", params)["values"]


def get_intraday(symbol: str, interval: str = "1h", from_date: str | None = None, to_date: str | None = None) -> list[dict]:
    params = {"symbol": symbol, "interval": interval}
    if from_date:
        params["start_date"] = from_date
    if to_date:
        params["end_date"] = to_date
    return _get("time_series", params)["values"]


if __name__ == "__main__":
    print(get_quote("AAPL"))
