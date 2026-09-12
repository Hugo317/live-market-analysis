import pandas as pd

NUMERIC_COLUMNS = ["open", "high", "low", "close", "volume", "change", "change_pct"]
REQUIRED_COLUMNS = ["region", "symbol", "timestamp", "close"]
OHLC_COLUMNS = ["open", "high", "low", "close"]

# A bar's open/close must lie within its own high/low by definition. Providers
# occasionally break this -- most often by a rounding whisker (split/dividend
# adjustment applied slightly differently per field), but yfinance's monthly
# interval (`apis/yahoo.py`'s deep-history pulls) has a known bug where `close`
# comes back scaled ~10-1000x off from an otherwise-consistent open/high/low
# for the same bar. Below this deviation, treat it as rounding noise and widen
# high/low to cover it (no data lost); above it, treat it as provider
# corruption and drop the bar outright (widening would just launder a bogus
# close into a bogus "high").
MAX_OHLC_DEVIATION = 0.5


def _outside_range_pct(df: pd.DataFrame, field: str) -> pd.Series:
    value = df[field]
    overshoot = (value < df["low"]) * (df["low"] - value) + (value > df["high"]) * (value - df["high"])
    return overshoot / value.abs().clip(lower=1e-9)


def fix_ohlc(df: pd.DataFrame) -> pd.DataFrame:
    ohlc = df[OHLC_COLUMNS]
    positive = (ohlc > 0).all(axis=1)  # real prices are never <= 0
    deviation = pd.concat([_outside_range_pct(df, "close"), _outside_range_pct(df, "open")], axis=1).max(axis=1)

    df = df[positive & (deviation <= MAX_OHLC_DEVIATION)].copy()
    ohlc = df[OHLC_COLUMNS]
    df["high"] = ohlc.max(axis=1)
    df["low"] = ohlc.min(axis=1)
    return df


def clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    for col in NUMERIC_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=REQUIRED_COLUMNS)
    df = df.drop_duplicates(subset=["region", "symbol", "timestamp"])
    df = fix_ohlc(df)
    df = df.sort_values("timestamp").reset_index(drop=True)

    return df


if __name__ == "__main__":
    from live_market_analysis.data_handling.merge import merge_quotes

    try:
        raw = merge_quotes()
        print(clean(raw))
    except FileNotFoundError as e:
        print(e)
