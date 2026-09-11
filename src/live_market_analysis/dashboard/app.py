import os

import plotly.express as px
from dash import Dash, Input, Output, State, ctx, dash_table, dcc, html

from live_market_analysis.data_handling import analyze
from live_market_analysis.data_handling.clean import clean
from live_market_analysis.data_handling.db import read_quotes, upsert_quotes
from live_market_analysis.data_handling.merge import merge_quotes
from live_market_analysis.data_handling.symbols import (
    get_asia_pairs,
    get_asia_symbol_names,
    get_europe_symbols,
    get_europe_symbol_names,
    get_us_symbols,
    get_us_symbol_names,
)
from live_market_analysis import fetch_raw, news

EODHD_SYMBOLS = get_europe_symbols()
TWELVE_DATA_SYMBOLS = get_us_symbols()
ITICK_PAIRS = get_asia_pairs()

# symbol -> company name, combined across all 3 regions (keyed by the same
# symbol string stored in the DB's `symbol` column).
SYMBOL_NAMES = {
    **get_europe_symbol_names(),
    **get_us_symbol_names(),
    **get_asia_symbol_names(),
}

# Options + provider dispatch for the historical trend-line dropdown.
SYMBOL_OPTIONS = []
SYMBOL_PROVIDER_MAP = {}

for _s in EODHD_SYMBOLS:
    _value = f"EU:{_s}"
    _name = SYMBOL_NAMES.get(_s, "")
    SYMBOL_OPTIONS.append({"label": f"{_s} - {_name}" if _name else _s, "value": _value})
    SYMBOL_PROVIDER_MAP[_value] = ("eodhd", _s)

for _s in TWELVE_DATA_SYMBOLS:
    _value = f"US:{_s}"
    _name = SYMBOL_NAMES.get(_s, "")
    SYMBOL_OPTIONS.append({"label": f"{_s} - {_name}" if _name else _s, "value": _value})
    SYMBOL_PROVIDER_MAP[_value] = ("twelve_data", _s)

for _region, _code in ITICK_PAIRS:
    _value = f"ASIA:{_region}:{_code}"
    _name = SYMBOL_NAMES.get(_code, "")
    SYMBOL_OPTIONS.append({"label": f"{_code} - {_name}" if _name else _code, "value": _value})
    SYMBOL_PROVIDER_MAP[_value] = ("itick", _region, _code)

REGION_TABS = ["Global", "US", "Europe", "Asia"]
REGION_CODE = {"US": "US", "Europe": "EU", "Asia": "ASIA"}

PERIOD_OPTIONS = [
    {"label": "Hourly", "value": "h"},
    {"label": "Daily", "value": "d"},
    {"label": "Weekly", "value": "w"},
    {"label": "Monthly", "value": "m"},
]

# This app is meant to be checked once a day, not left open continuously.
# Twelve Data's free tier is 800 calls/day and has no batch quote endpoint
# (20 US symbols = 20 calls per refresh), so a short auto-refresh interval
# would blow the daily quota well before the day is over. The auto-refresh
# here is just a safety net for a long-open tab; real refreshes should come
# from the "Refresh now" button or a fresh page load.
REFRESH_INTERVAL_MS = 24 * 60 * 60 * 1000


def _with_company(df):
    df = df.copy()
    df["company"] = df["symbol"].map(SYMBOL_NAMES).fillna("")
    return df


def _latest_per_symbol(df):
    """Collapses a multi-row-per-symbol historical DataFrame down to the most
    recent bar per (region, symbol), for views that want "current standing"
    (top gainers, top by volume, top by volatility, region growth, and the
    click-through quotes table) rather than every historical bar ever fetched.

    ASSUMPTION: analyze.py does not yet expose this as of when this was
    written; if/when data-handler adds `analyze.latest_per_symbol`, this
    prefers that (so the two implementations don't diverge) and only falls
    back to the inline groupby if it's absent.
    """
    fn = getattr(analyze, "latest_per_symbol", None)
    if fn is not None:
        return fn(df)
    if df.empty:
        return df
    return df.sort_values("timestamp").groupby(["region", "symbol"], as_index=False).tail(1)


def _region_symbol_for(provider_info):
    """Maps a SYMBOL_PROVIDER_MAP tuple to the (region, symbol) key used in the
    `quotes` table, per merge.py's normalization (EU keeps the EODHD ticker, US
    keeps the Twelve Data ticker, ASIA keeps the iTick numeric code)."""
    provider = provider_info[0]
    if provider == "eodhd":
        return "EU", provider_info[1]
    if provider == "twelve_data":
        return "US", provider_info[1]
    if provider == "itick":
        return "ASIA", provider_info[2]
    return None, None


def _news_list(stories):
    items = []
    for s in stories:
        content = [html.Span(s["title"])]
        if s.get("thumbnail"):
            content.insert(0, html.Img(src=s["thumbnail"], style={"height": "80px", "verticalAlign": "middle", "marginRight": "8px"}))
        items.append(html.Li(html.A(content, href=s["link"], target="_blank", style={"display": "flex", "alignItems": "center"})))
    return items


app = Dash(__name__)

app.layout = html.Div(
    [
        html.H1("Live Market Analysis"),
        html.P(
            "This dashboard is historical-only: there is no live quote feed. "
            "\"Refresh now\" (and the once-a-day auto-refresh timer) bulk-fetches daily "
            "historical bars for US + Asia only. Europe (EODHD) is never bulk-fetched -- "
            "its free tier caps out at 20 calls/day total with no batch endpoint, so EU "
            "data only updates one symbol at a time when you look it up in Historical "
            "Trend below."
        ),
        html.Button("Refresh now (US + Asia)", id="refresh-button", n_clicks=0),
        dcc.Interval(id="refresh-interval", interval=REFRESH_INTERVAL_MS, n_intervals=0),
        html.Div(id="fetch-error", style={"color": "red"}),
        html.H2("Historical Trend"),
        html.P(
            "Pick any tracked symbol to chart its historical closing prices. Selecting a "
            "symbol also persists the fetched bars to the database, so browsing here is "
            "how Europe's coverage grows over time (each EU pick costs 1 of EODHD's 20 "
            "daily calls)."
        ),
        dcc.Dropdown(id="trend-symbol-selector", options=SYMBOL_OPTIONS, placeholder="Select a symbol..."),
        html.Div(id="trend-status", style={"color": "red"}),
        dcc.Loading(dcc.Graph(id="trend-chart")),
        html.H2("Latest Snapshot"),
        dcc.Tabs(id="region-tabs", value="Global", children=[dcc.Tab(label=tab, value=tab) for tab in REGION_TABS]),
        dcc.Loading(dcc.Graph(id="change-pct-chart")),
        html.H3("Latest Data (click a row for company news)"),
        html.P(
            "One row per symbol -- the most recent historical bar on file. Europe rows "
            "only appear here once you've looked that symbol up in Historical Trend above."
        ),
        dcc.Loading(dash_table.DataTable(id="quotes-table", page_size=20, row_selectable=False, cell_selectable=True)),
        html.Div(id="company-news"),
        html.H2("Top Gainers"),
        dash_table.DataTable(id="top-gainers-table"),
        html.H2("Top by Volume"),
        dcc.Graph(id="volume-chart"),
        html.H2("Top by Volatility (High-Low Range %)"),
        dcc.Graph(id="volatility-chart"),
        html.H2("Region Performance"),
        dcc.Graph(id="region-growth-chart"),
        html.H2("Top Stories"),
        html.Ul(id="top-stories"),
        html.H2("Growth by Period (US + Asia)"),
        html.P(
            "Europe is excluded from this (and every other per-symbol-looped historical "
            "view) for the same reason as the bulk refresh above: EODHD's 20-calls/day cap "
            "would be exhausted by looping all tracked EU symbols in one switch. Look up "
            "individual EU symbols in Historical Trend instead."
        ),
        dcc.RadioItems(id="period-selector", options=PERIOD_OPTIONS, value="d", inline=True),
        html.Div(id="period-growth-status", style={"color": "red"}),
        dcc.Loading(dash_table.DataTable(id="period-growth-table", page_size=20)),
    ]
)


def fetch_and_store() -> None:
    """Bulk daily refresh for US + Asia only. Europe/EODHD is deliberately never
    touched here -- see fetch_raw.fetch_bulk_historical's docstring and the
    on-demand EU path in update_trend_chart below."""
    fetch_raw.fetch_bulk_historical(
        twelve_data_symbols=TWELVE_DATA_SYMBOLS,
        itick_pairs=ITICK_PAIRS,
        period="d",
    )
    upsert_quotes(clean(merge_quotes()))


@app.callback(
    Output("change-pct-chart", "figure"),
    Output("quotes-table", "data"),
    Output("top-gainers-table", "data"),
    Output("volume-chart", "figure"),
    Output("volatility-chart", "figure"),
    Output("region-growth-chart", "figure"),
    Output("top-stories", "children"),
    Output("fetch-error", "children"),
    Input("region-tabs", "value"),
    Input("refresh-button", "n_clicks"),
    Input("refresh-interval", "n_intervals"),
)
def update_dashboard(region_tab: str, _n_clicks: int, _n_intervals: int):
    error_message = ""

    if ctx.triggered_id in ("refresh-button", "refresh-interval", None):
        try:
            fetch_and_store()
        except Exception as e:
            error_message = f"Refresh failed, showing last known data: {e}"

    region = REGION_CODE.get(region_tab)
    df = read_quotes(region=region)
    all_quotes = read_quotes()

    # Each symbol now has many historical rows (one per bar), so every "current
    # standing" view below (bar chart, latest-data table, gainers, volume,
    # volatility, region growth) is computed against the most recent bar per
    # symbol rather than the raw multi-row history.
    latest_tab = _latest_per_symbol(df)
    latest_all = _latest_per_symbol(all_quotes)

    fig = px.bar(latest_tab, x="symbol", y="change_pct", color="region", title="Latest change % by symbol")

    if not latest_all.empty:
        gainers = _with_company(analyze.top_gainers(latest_all, 5))
        volume_df = _with_company(analyze.top_by_volume(latest_all, 10))
        volatility_df = _with_company(analyze.top_volatility(latest_all, 10))
        region_perf = analyze.region_growth(latest_all)
    else:
        gainers = latest_all
        volume_df = latest_all
        volatility_df = latest_all
        region_perf = latest_all

    volume_fig = px.bar(volume_df, x="symbol", y="volume", color="region", title="Top 10 by volume", hover_data=["company"])
    volatility_fig = px.bar(
        volatility_df, x="symbol", y="range_pct", color="region", title="Top 10 by intraday range %", hover_data=["company"]
    )
    region_fig = px.bar(region_perf, x="region", y="change_pct", title="Average change % by region")

    try:
        stories = news.get_top_stories(5)
        story_items = _news_list(stories)
    except Exception as e:
        story_items = []
        error_message = (error_message + f" Top stories unavailable: {e}").strip()

    quotes_with_company = _with_company(latest_tab) if not latest_tab.empty else latest_tab

    return (
        fig,
        quotes_with_company.to_dict("records"),
        gainers.to_dict("records"),
        volume_fig,
        volatility_fig,
        region_fig,
        story_items,
        error_message,
    )


@app.callback(
    Output("company-news", "children"),
    Input("quotes-table", "active_cell"),
    State("quotes-table", "data"),
)
def show_company_news(active_cell, table_data):
    if not active_cell or not table_data:
        return None

    row = table_data[active_cell["row"]]
    symbol = row["symbol"]

    try:
        stories = news.get_company_news(symbol, count=5)
    except Exception as e:
        return html.P(f"Could not load news for {symbol}: {e}")

    if not stories:
        return html.P(f"No news found for {symbol}.")

    return html.Div(
        [
            html.H3(f"News for {symbol}"),
            html.Ul(_news_list(stories)),
        ]
    )


@app.callback(
    Output("period-growth-table", "data"),
    Output("period-growth-status", "children"),
    Input("period-selector", "value"),
)
def update_period_growth(period: str):
    try:
        df = analyze.period_growth_all(TWELVE_DATA_SYMBOLS, ITICK_PAIRS, period=period)
    except Exception as e:
        return [], f"Failed to load growth-by-period data: {e}"

    n_errors = df["error"].notna().sum() if "error" in df else 0
    status = f"{n_errors} symbol(s) unavailable for this period." if n_errors else ""
    return df.to_dict("records"), status


@app.callback(
    Output("trend-chart", "figure"),
    Output("trend-status", "children"),
    Input("trend-symbol-selector", "value"),
)
def update_trend_chart(value: str | None):
    if not value:
        return px.line(title="Select a symbol above"), ""

    provider_info = SYMBOL_PROVIDER_MAP.get(value)
    if provider_info is None:
        return px.line(title="Unknown symbol"), f"'{value}' is not a tracked symbol."

    status = ""
    if provider_info[0] == "eodhd":
        status = "Note: this used 1 of EODHD's 20 daily API calls."

    # Fetch + persist (fetch_symbol_historical only writes data/raw/*.json, so we
    # still run the usual merge -> clean -> upsert step to land it in the DB).
    # We then chart straight from the DB rather than calling
    # analyze.get_symbol_history separately, so picking a symbol here costs
    # exactly one provider API call, not two -- important for EODHD's 20/day cap.
    try:
        fetch_raw.fetch_symbol_historical(*provider_info, period="d")
        upsert_quotes(clean(merge_quotes()))
    except Exception as e:
        status = (status + f" Failed to fetch/persist fresh data for {value}: {e}").strip()

    region, symbol = _region_symbol_for(provider_info)
    history = read_quotes(region=region)
    if not history.empty:
        history = history[history["symbol"] == symbol].sort_values("timestamp")

    if history.empty:
        message = status or f"No historical data available yet for {value}."
        return px.line(title=f"No data for {value}"), message

    fig = px.line(history, x="timestamp", y="close", title=f"{value} closing price (daily)")
    return fig, status


if __name__ == "__main__":
    debug = os.environ.get("DASHBOARD_DEBUG", "false").lower() == "true"
    app.run(debug=debug)
