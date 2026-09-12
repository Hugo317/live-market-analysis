import yfinance as yf

MARKET_INDEX = "^GSPC"

# One representative index per tracked region, for the dashboard's per-region
# "Top Stories" sections. Global and US deliberately use different tickers
# (^GSPC vs ^DJI) -- yfinance tags the same major-market story to multiple
# related index tickers, so reusing one ticker for both made the two sections
# show near-identical stories.
REGION_INDEX = {
    "Global": "^GSPC",
    "US": "^DJI",
    "Europe": "^STOXX50E",
    "Asia": "^HSI",
}


def _normalize_news_item(item: dict) -> dict:
    """yfinance's news schema has changed across versions (flat vs. nested under
    'content'), so extract defensively rather than assuming one shape."""
    content = item.get("content", item)

    title = content.get("title")

    provider = content.get("provider")
    publisher = provider.get("displayName") if isinstance(provider, dict) else content.get("publisher")

    link = content.get("canonicalUrl")
    if isinstance(link, dict):
        link = link.get("url")
    if not link:
        link = content.get("link")

    published = content.get("pubDate") or content.get("providerPublishTime")

    thumbnail = None
    thumb = content.get("thumbnail")
    if isinstance(thumb, dict):
        small = next((r["url"] for r in thumb.get("resolutions", []) if r.get("tag") == "170x128"), None)
        thumbnail = small or thumb.get("originalUrl")

    return {
        "title": title,
        "publisher": publisher,
        "link": link,
        "published": published,
        "thumbnail": thumbnail,
    }


def get_company_news(symbol: str, count: int = 5) -> list[dict]:
    items = yf.Ticker(symbol).get_news(count=count)
    return [_normalize_news_item(item) for item in items]


def get_top_stories(count: int = 5, index: str = MARKET_INDEX) -> list[dict]:
    items = yf.Ticker(index).get_news(count=count)
    return [_normalize_news_item(item) for item in items]


if __name__ == "__main__":
    print("Company news (AAPL):")
    for story in get_company_news("AAPL"):
        print(story)

    print("\nTop stories:")
    for story in get_top_stories():
        print(story)
