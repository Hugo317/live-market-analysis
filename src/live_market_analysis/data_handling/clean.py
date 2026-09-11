import pandas as pd

NUMERIC_COLUMNS = ["open", "high", "low", "close", "volume", "change", "change_pct"]
REQUIRED_COLUMNS = ["region", "symbol", "timestamp", "close"]


def clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    for col in NUMERIC_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=REQUIRED_COLUMNS)
    df = df.drop_duplicates(subset=["region", "symbol", "timestamp"])
    df = df.sort_values("timestamp").reset_index(drop=True)

    return df


if __name__ == "__main__":
    from live_market_analysis.data_handling.merge import merge_quotes

    try:
        raw = merge_quotes()
        print(clean(raw))
    except FileNotFoundError as e:
        print(e)
