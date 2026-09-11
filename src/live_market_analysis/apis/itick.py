import os

import requests
from dotenv import load_dotenv

from live_market_analysis.data_handling.cache import cached_get
from live_market_analysis.data_handling.rate_limiter import RateLimiter

load_dotenv()

BASE_URL = "https://api-free.itick.org"

PERIOD_TO_K_TYPE = {"d": 8, "w": 9, "m": 10}
INTRADAY_K_TYPE = 5  # 60 minutes

# Free plan limit is 5 calls/minute.
_limiter = RateLimiter(calls_per_minute=5)


def _fetch(path: str, params: dict) -> dict:
    _limiter.wait()
    api_key = os.environ["I_TICK_API_KEY"]
    response = requests.get(
        f"{BASE_URL}/{path}",
        params=params,
        headers={"accept": "application/json", "token": api_key},
    )
    if not response.ok:
        raise requests.exceptions.HTTPError(
            f"{response.status_code} error: {response.text}", response=response
        )
    return response.json()


def _get(path: str, params: dict) -> dict:
    return cached_get("itick", path, params, lambda: _fetch(path, params))


def get_quote(region: str, code: str) -> dict:
    return _get("stock/quote", {"region": region, "code": code})


def get_quotes(pairs: list[tuple[str, str]]) -> list[dict]:
    return [get_quote(region, code) for region, code in pairs]


def get_historical(region: str, code: str, period: str = "d", limit: int = 30) -> dict:
    return _get(
        "stock/kline",
        {"region": region, "code": code, "kType": PERIOD_TO_K_TYPE[period], "limit": limit},
    )


def get_intraday(region: str, code: str, limit: int = 30) -> dict:
    return _get(
        "stock/kline",
        {"region": region, "code": code, "kType": INTRADAY_K_TYPE, "limit": limit},
    )


if __name__ == "__main__":
    print(get_quote("HK", "700"))
