import hashlib
import json
from pathlib import Path
from typing import Callable

CACHE_DIR = Path(__file__).resolve().parents[3] / ".cache"


def cached_get(provider: str, path: str, params: dict, fetch_fn: Callable[[], dict | list]) -> dict | list:
    CACHE_DIR.mkdir(exist_ok=True)
    key = hashlib.sha256(f"{provider}:{path}:{sorted(params.items())}".encode()).hexdigest()
    cache_file = CACHE_DIR / f"{provider}_{key}.json"

    if cache_file.exists():
        return json.loads(cache_file.read_text())

    result = fetch_fn()
    cache_file.write_text(json.dumps(result))
    return result
