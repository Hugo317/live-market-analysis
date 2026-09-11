import json
import os
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

from live_market_analysis.data_handling.cache import cached_get

load_dotenv()

BASE_URL = "https://eodhd.com/api"
IS_PREMIUM = os.environ.get("EODHD_IS_PREMIUM", "false").lower() == "true"

# EODHD's free plan is capped at 20 API calls per day (UTC), not per-minute like
# the other 2 providers. Historical calls aren't batched, so this budget is easy
# to blow through in a single call (e.g. looping 20 symbols). Track and enforce
# it locally so we fail fast with a clear message instead of silently burning
# the whole day's quota or getting an opaque error from the provider.
DAILY_CALL_LIMIT = 20
_BUDGET_FILE = Path(__file__).resolve().parents[3] / ".cache" / "eodhd_daily_calls.json"


def _check_and_record_daily_call() -> None:
    if IS_PREMIUM:
        return  # paid plans have a much higher daily cap; not worth tracking here

    _BUDGET_FILE.parent.mkdir(parents=True, exist_ok=True)
    today = str(datetime.now(timezone.utc).date())

    data = {}
    if _BUDGET_FILE.exists():
        data = json.loads(_BUDGET_FILE.read_text())

    count = data.get(today, 0)
    if count >= DAILY_CALL_LIMIT:
        raise RuntimeError(
            f"EODHD free-tier daily call budget ({DAILY_CALL_LIMIT}/day) already used today ({today} UTC). "
            "Wait until the next UTC day, or set EODHD_IS_PREMIUM=true in .env if you've upgraded."
        )

    _BUDGET_FILE.write_text(json.dumps({today: count + 1}))


def _fetch(path: str, params: dict) -> dict | list:
    _check_and_record_daily_call()
    api_key = os.environ["EODHD_API_KEY"]
    response = requests.get(
        f"{BASE_URL}/{path}",
        params={**params, "api_token": api_key, "fmt": "json"},
    )
    if not response.ok:
        raise requests.exceptions.HTTPError(
            f"{response.status_code} error: {response.text}", response=response
        )
    return response.json()


def _get(path: str, params: dict) -> dict | list:
    return cached_get("eodhd", path, params, lambda: _fetch(path, params))


def get_quotes(symbols: list[str]) -> list[dict]:
    first, *rest = symbols
    params = {"s": ",".join(rest)} if rest else {}
    result = _get(f"real-time/{first}", params)
    return result if isinstance(result, list) else [result]


def get_historical(symbol: str, period: str = "d", from_date: str | None = None, to_date: str | None = None) -> list[dict]:
    params = {"period": period}
    if from_date:
        params["from"] = from_date
    if to_date:
        params["to"] = to_date
    return _get(f"eod/{symbol}", params)


def get_intraday(symbol: str, interval: str = "1h", from_ts: int | None = None, to_ts: int | None = None) -> list[dict]:
    if not IS_PREMIUM:
        raise RuntimeError(
            "Intraday/hourly data requires an EODHD premium plan. "
            "Set EODHD_IS_PREMIUM=true in .env once upgraded."
        )
    params = {"interval": interval}
    if from_ts:
        params["from"] = from_ts
    if to_ts:
        params["to"] = to_ts
    return _get(f"intraday/{symbol}", params)


if __name__ == "__main__":
    print(get_quotes(["VOD.LSE"]))
