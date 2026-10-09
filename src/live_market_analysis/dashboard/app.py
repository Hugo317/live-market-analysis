import base64
import os

import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
from dash import Dash, Input, Output, State, dash_table, dcc, html
from dash.dash_table.Format import Format, Group, Scheme, Sign

from live_market_analysis.data_handling import analyze
from live_market_analysis.data_handling.db import IS_SNAPSHOT, read_latest_quotes, read_recent_bars, read_symbol_history
from live_market_analysis.data_handling.symbols import (
    get_asia_pairs,
    get_asia_symbol_names,
    get_europe_symbols,
    get_europe_symbol_names,
    get_us_symbols,
    get_us_symbol_names,
)
from live_market_analysis import news
from live_market_analysis.apis import yahoo

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

# Options for the historical trend-line dropdown, tagged with the region tab
# each belongs to so the dropdown can be filtered per-tab.
SYMBOL_OPTIONS = []

for _s in EODHD_SYMBOLS:
    _name = SYMBOL_NAMES.get(_s, "")
    SYMBOL_OPTIONS.append({"label": f"{_s} - {_name}" if _name else _s, "value": _s, "region": "Europe"})

for _s in TWELVE_DATA_SYMBOLS:
    _name = SYMBOL_NAMES.get(_s, "")
    SYMBOL_OPTIONS.append({"label": f"{_s} - {_name}" if _name else _s, "value": _s, "region": "US"})

for _region, _code in ITICK_PAIRS:
    _name = SYMBOL_NAMES.get(_code, "")
    SYMBOL_OPTIONS.append({"label": f"{_code} - {_name}" if _name else _code, "value": _code, "region": "Asia"})

# symbol -> DB region code ("EU"/"US"/"ASIA"), so the trend chart can query
# just that one symbol's rows instead of scanning the whole table.
_TAB_TO_REGION_CODE = {"Europe": "EU", "US": "US", "Asia": "ASIA"}
SYMBOL_REGION_CODE = {o["value"]: _TAB_TO_REGION_CODE[o["region"]] for o in SYMBOL_OPTIONS}


def _yahoo_ticker(symbol: str) -> str:
    """Our stored symbols follow each provider's own convention (EODHD's
    'III.LSE', iTick's bare '700'), neither of which yfinance understands --
    convert to yfinance's ticker format before calling news.get_company_news,
    same conversion `apis/yahoo.py` already uses for the backfill script."""
    region = SYMBOL_REGION_CODE.get(symbol)
    if region == "EU":
        return yahoo.to_eu_ticker(symbol)
    if region == "ASIA":
        return yahoo.to_asia_ticker(symbol)
    return symbol

REGION_TABS = ["Global", "US", "Europe", "Asia"]
REGION_CODE = {"US": "US", "Europe": "EU", "Asia": "ASIA"}

# ---------------------------------------------------------------------------
# Design tokens (mirrors assets/style.css) -- kept in sync by hand since
# Plotly figures can't read CSS custom properties.
# ---------------------------------------------------------------------------
SURFACE = "#1a1a19"
GRIDLINE = "#2c2c2a"
BASELINE = "#383835"
TEXT_SECONDARY = "#c3c2b7"
TEXT_MUTED = "#898781"
ACCENT = "#da7756"
GOOD = "#0ca30c"
CRITICAL = "#e66767"
SEQUENTIAL_BLUE = "#3987e5"
FONT_SANS = "-apple-system, BlinkMacSystemFont, Segoe UI, Helvetica, Arial, sans-serif"

pio.templates["market_dark"] = go.layout.Template(
    layout=go.Layout(
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        font=dict(family=FONT_SANS, color=TEXT_SECONDARY, size=12),
        title=dict(font=dict(color="#ffffff", size=14)),
        xaxis=dict(gridcolor=GRIDLINE, linecolor=BASELINE, zerolinecolor=BASELINE, color=TEXT_MUTED),
        yaxis=dict(gridcolor=GRIDLINE, linecolor=BASELINE, zerolinecolor=BASELINE, color=TEXT_MUTED),
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color=TEXT_SECONDARY)),
        margin=dict(t=48, r=24, l=48, b=40),
        hoverlabel=dict(bgcolor="#202020", font=dict(color="#ffffff", family=FONT_SANS), bordercolor=BASELINE),
    )
)
pio.templates.default = "market_dark"


def _empty_state(message: str, icon: str = "\U0001f4ed") -> html.Div:
    return html.Div(
        [html.Div(icon, className="empty-icon"), html.Span(message)],
        className="empty-state",
    )


def _empty_figure(message: str) -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(
        text=message,
        showarrow=False,
        font=dict(color=TEXT_MUTED, size=13),
        xref="paper",
        yref="paper",
        x=0.5,
        y=0.5,
    )
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return fig


def _sign_colors(values) -> list[str]:
    return [GOOD if v >= 0 else CRITICAL for v in values]


_SPARK_CHARS = "▁▂▃▄▅▆▇█"  # ▁▂▃▄▅▆▇█


def _sparkline_text(closes: list[float]) -> str:
    """Plain-text sparkline using Unicode block characters. dash_table's
    markdown cell renderer doesn't render `data:` URI images (it just prints
    the raw markdown source, e.g. "![trend](data:image/svg+xml;base64,...)"
    as literal text) so an inline SVG image never actually worked here --
    this renders correctly with zero extra markup."""
    if len(closes) < 2:
        return ""
    lo, hi = min(closes), max(closes)
    span = (hi - lo) or 1.0
    return "".join(_SPARK_CHARS[min(len(_SPARK_CHARS) - 1, int((c - lo) / span * (len(_SPARK_CHARS) - 1)))] for c in closes)


def _with_sparkline(latest_df: pd.DataFrame, history_df: pd.DataFrame) -> pd.DataFrame:
    """Adds a `trend` text-sparkline column to `latest_df` using each symbol's
    last ~15 closes from `history_df` (the multi-row historical DataFrame)."""
    if latest_df.empty:
        latest_df = latest_df.copy()
        latest_df["trend"] = []
        return latest_df

    sparkline_by_symbol = {}
    if not history_df.empty:
        for (_region, symbol), rows in history_df.sort_values("timestamp").groupby(["region", "symbol"]):
            closes = rows["close"].tail(15).tolist()
            sparkline_by_symbol[symbol] = _sparkline_text(closes)

    out = latest_df.copy()
    out["trend"] = out["symbol"].map(sparkline_by_symbol).fillna("")
    return out


def _display_symbol(region: str, symbol: str) -> str:
    """Human-readable symbol for tables/charts. iTick's Asia codes are bare
    numbers (e.g. '700') with no exchange suffix, unlike EU ('III.LSE') and
    US ('AAPL') symbols -- read on its own a bare number looks like a typo or
    an unlabeled ID, so suffix it the same way EU/Yahoo already do."""
    return f"{symbol}.HK" if region == "ASIA" else symbol


def _with_company(df):
    df = df.copy()
    df["company"] = df["symbol"].map(SYMBOL_NAMES).fillna("")
    df["symbol_display"] = [_display_symbol(r, s) for r, s in zip(df["region"], df["symbol"])]
    return df


def _news_placeholder_image() -> str:
    """Inline SVG used in place of a thumbnail -- yfinance doesn't attach one
    to every story (regional/Asia tickers especially), and a news grid with
    some cards imaged and others bare text looks broken rather than varied."""
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="300" height="170" viewBox="0 0 300 170">'
        f'<rect width="300" height="170" fill="{SURFACE}"/>'
        f'<g stroke="{ACCENT}" stroke-width="4" fill="none" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M85 112 L118 68 L148 94 L180 52 L215 88"/>'
        f'<circle cx="215" cy="88" r="5" fill="{ACCENT}" stroke="none"/>'
        "</g></svg>"
    )
    encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


_NEWS_PLACEHOLDER = _news_placeholder_image()


def _news_list(stories):
    cards = []
    for s in stories:
        children = [
            html.Img(src=s.get("thumbnail") or _NEWS_PLACEHOLDER, className="news-card-image"),
            html.Span(s["title"], className="news-card-title"),
        ]
        cards.append(html.Li(html.A(children, href=s["link"], target="_blank", className="news-card")))
    return cards


def _stat_card(label: str, value: str, sub: str = "", tone: str = "") -> html.Div:
    return html.Div(
        [
            html.P(label, className="stat-label"),
            html.P(value, className=f"stat-value {tone}".strip()),
            html.P(sub, className="stat-sub") if sub else None,
        ],
        className="stat-card",
    )


app = Dash(__name__)
server = app.server  # WSGI entry point for gunicorn

app.layout = html.Div(
    [
        html.Div(
            [
                html.Div("\U0001f4c8", className="app-logo"),
                html.Div(
                    [
                        html.P("Live Market Analysis", className="app-title"),
                        html.P("Historical data · US, Europe & Asia", className="app-subtitle"),
                    ]
                ),
            ],
            className="app-header",
        ),
        html.Div(
            [
                html.P(
                    "Static demo: because of API pulling restrictions, the data here is a stored snapshot "
                    "(daily bars up to 11 Sep 2026) and nothing is fetched live."
                    if IS_SNAPSHOT
                    else "Read-only over the local database — no live/refresh calls, ever. Browsing, "
                    "switching tabs, and picking symbols only re-reads what's already stored. To "
                    "grow the database, run scripts/backfill_db.py separately (it makes real API "
                    "calls and is never triggered from here).",
                    className="section-note",
                    style={"margin": "0 0 20px"},
                ),
                dcc.Tabs(
                    id="region-tabs",
                    value="Global",
                    className="dash-tabs",
                    children=[dcc.Tab(label=tab, value=tab, className="tab", selected_className="tab--selected") for tab in REGION_TABS],
                    style={"marginBottom": "24px"},
                ),
                html.Div(id="hero-stats", className="hero-row"),
                html.Div(
                    [
                        html.P("Historical Trend", className="section-title"),
                        html.P(
                            "Search a tracked symbol to chart its stored historical closing prices.",
                            className="section-note",
                        ),
                        dcc.Dropdown(
                            id="trend-symbol-selector",
                            options=SYMBOL_OPTIONS,
                            placeholder="Search symbols…",
                            className="symbol-search",
                        ),
                        dcc.Loading(dcc.Graph(id="trend-chart"), type="circle", color=ACCENT),
                    ],
                    className="section-card",
                ),
                html.Div(
                    [
                        html.P(id="change-pct-title", className="section-title"),
                        dcc.Loading(dcc.Graph(id="change-pct-chart"), type="circle", color=ACCENT),
                    ],
                    className="section-card",
                ),
                html.Div(
                    [
                        html.P(id="quotes-table-title", className="section-title"),
                        html.P(
                            "Top 20 symbols by latest change %, most upward first, with a "
                            "15-bar trend sparkline. Click a row for company news.",
                            className="section-note",
                        ),
                        dcc.Loading(html.Div(id="quotes-table-wrapper"), type="circle", color=ACCENT),
                        html.Div(id="company-news"),
                    ],
                    className="section-card",
                ),
                html.Div(
                    [
                        html.P(id="gainers-title", className="section-title"),
                        dcc.Loading(html.Div(id="top-gainers-wrapper"), type="circle", color=ACCENT),
                    ],
                    className="section-card",
                ),
                html.Div(
                    [
                        html.P(id="volume-title", className="section-title"),
                        dcc.Loading(dcc.Graph(id="volume-chart"), type="circle", color=ACCENT),
                    ],
                    className="section-card",
                ),
                html.Div(
                    [
                        html.P(id="volatility-title", className="section-title"),
                        dcc.Loading(dcc.Graph(id="volatility-chart"), type="circle", color=ACCENT),
                    ],
                    className="section-card",
                ),
                html.Div(
                    [
                        html.P("Region Performance", className="section-title"),
                        html.P(
                            "Compares all 3 regions at once — only shown on the Global tab.",
                            className="section-note",
                        ),
                        dcc.Loading(html.Div(id="region-growth-wrapper"), type="circle", color=ACCENT),
                    ],
                    className="section-card",
                ),
                dcc.Store(id="news-store"),
                html.Div(
                    [
                        html.P(id="top-stories-title", className="section-title"),
                        html.Ul(id="top-stories", className="news-grid"),
                    ],
                    className="section-card",
                ),
            ],
            className="app-shell",
        ),
    ]
)


# Raw provider floats carry full IEEE-754 noise (e.g. 8.710000038146973 for
# what iTick actually reports as 8.71) -- format numeric columns instead of
# showing that noise verbatim.
_PRICE_FORMAT = Format(precision=2, scheme=Scheme.fixed)
_PCT_FORMAT = Format(precision=2, scheme=Scheme.fixed, sign=Sign.positive)
_VOLUME_FORMAT = Format(precision=0, scheme=Scheme.fixed, group=Group.yes)
_NUMERIC_FORMATS = {
    "open": _PRICE_FORMAT,
    "high": _PRICE_FORMAT,
    "low": _PRICE_FORMAT,
    "close": _PRICE_FORMAT,
    "change": _PRICE_FORMAT,
    "change_pct": _PCT_FORMAT,
    "range_pct": _PCT_FORMAT,
    "volume": _VOLUME_FORMAT,
}


def _column_def(col_id: str, name: str) -> dict:
    fmt = _NUMERIC_FORMATS.get(col_id)
    return {"name": name, "id": col_id, "type": "numeric", "format": fmt} if fmt else {"name": name, "id": col_id}


def _dark_table(id_: str, data, columns, centered_cols: tuple[str, ...] = ()) -> dash_table.DataTable:
    return dash_table.DataTable(
        id=id_,
        data=data,
        columns=columns,
        page_size=20,
        cell_selectable="quotes" in id_,
        style_header={
            "backgroundColor": "#202020",
            "color": TEXT_MUTED,
            "border": "none",
            "borderBottom": f"1px solid {GRIDLINE}",
            "textTransform": "uppercase",
            "fontSize": "12px",
        },
        style_cell={
            "backgroundColor": SURFACE,
            "color": "#ffffff",
            "border": "none",
            "borderBottom": f"1px solid {GRIDLINE}",
            "fontFamily": FONT_SANS,
            "fontSize": "13px",
            "padding": "8px 10px",
        },
        style_cell_conditional=[
            {"if": {"column_id": c}, "fontFamily": "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"}
            for c in (
                "symbol",
                "symbol_display",
                "timestamp",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "change",
                "change_pct",
                "range_pct",
                "trend",
            )
        ]
        + [{"if": {"column_id": c}, "textAlign": "center", "padding": "2px"} for c in centered_cols],
        style_data_conditional=[
            {"if": {"filter_query": "{change_pct} >= 0", "column_id": "change_pct"}, "color": GOOD},
            {"if": {"filter_query": "{change_pct} < 0", "column_id": "change_pct"}, "color": CRITICAL},
            {"if": {"filter_query": "{change} >= 0", "column_id": "change"}, "color": GOOD},
            {"if": {"filter_query": "{change} < 0", "column_id": "change"}, "color": CRITICAL},
        ],
        style_table={"overflowX": "auto"},
    )


@app.callback(
    Output("hero-stats", "children"),
    Output("change-pct-title", "children"),
    Output("change-pct-chart", "figure"),
    Output("quotes-table-title", "children"),
    Output("quotes-table-wrapper", "children"),
    Output("gainers-title", "children"),
    Output("top-gainers-wrapper", "children"),
    Output("volume-title", "children"),
    Output("volume-chart", "figure"),
    Output("volatility-title", "children"),
    Output("volatility-chart", "figure"),
    Output("region-growth-wrapper", "children"),
    Output("trend-symbol-selector", "options"),
    Output("trend-symbol-selector", "value"),
    Input("region-tabs", "value"),
)
def update_dashboard(region_tab: str):
    scope_label = "Global" if region_tab == "Global" else region_tab
    region = REGION_CODE.get(region_tab)

    # Each symbol has many historical rows (one per bar) -- millions across
    # the whole table -- so every "current standing" view below (bar chart,
    # latest-data table, gainers, volume, volatility) asks the DB for just
    # the most recent bar per symbol directly (via read_latest_quotes' SQL
    # window function) rather than loading the full history into pandas.
    latest_tab = read_latest_quotes(region=region)

    hero = [
        _stat_card(f"Symbols Tracked ({scope_label})", str(len(latest_tab)) if not latest_tab.empty else "0"),
        _stat_card(
            "Data As Of",
            latest_tab["timestamp"].max().strftime("%b %d, %Y") if not latest_tab.empty else "—",
        ),
    ]
    # Same filtering as the Top Gainers table below (excludes stale
    # zero-volume prints) so the hero card, the table, and the preloaded
    # trend chart all agree on who "the" top gainer is.
    top_gainer_row = analyze.top_gainers(latest_tab, 1) if not latest_tab.empty else latest_tab
    if not top_gainer_row.empty:
        top_row = top_gainer_row.iloc[0]
        tone = "good" if top_row["change_pct"] >= 0 else "critical"
        top_gainer_symbol = top_row["symbol"]
        hero.append(
            _stat_card(
                "Top Gainer",
                f"{top_row['symbol']} {top_row['change_pct']:+.2f}%",
                sub=SYMBOL_NAMES.get(top_row["symbol"], ""),
                tone=tone,
            )
        )
    else:
        top_gainer_symbol = None
        hero.append(_stat_card("Top Gainer", "—"))

    if latest_tab.empty:
        change_fig = _empty_figure(f"No stored data for {scope_label} yet.")
    else:
        # With up to 485 symbols, one bar per symbol is unreadable -- bucket
        # into a change_pct distribution histogram instead.
        change_fig = go.Figure(
            go.Histogram(
                x=latest_tab["change_pct"],
                marker_color=SEQUENTIAL_BLUE,
                hovertemplate="Change: %{x:.1f}%<br>Symbols: %{y}<extra></extra>",
            )
        )
        change_fig.update_layout(
            title=f"Latest change % distribution — {scope_label} ({len(latest_tab)} symbols)",
            xaxis_title="Change %",
            yaxis_title="Symbols",
            showlegend=False,
            bargap=0.05,
        )

    if not latest_tab.empty:
        gainers = _with_company(analyze.top_gainers(latest_tab, 5))
        volume_df = _with_company(analyze.top_by_volume(latest_tab, 10))
        volatility_df = _with_company(analyze.top_volatility(latest_tab, 10))
    else:
        gainers = latest_tab
        volume_df = latest_tab
        volatility_df = latest_tab

    if volume_df.empty:
        volume_fig = _empty_figure(f"No volume data for {scope_label} yet.")
    else:
        volume_fig = go.Figure(
            go.Bar(
                x=volume_df["symbol_display"],
                y=volume_df["volume"],
                marker_color=SEQUENTIAL_BLUE,
                customdata=volume_df["company"],
                hovertemplate="%{x} — %{customdata}<br>Volume: %{y:,.0f}<extra></extra>",
            )
        )
        volume_fig.update_layout(title=f"Top 10 by volume — {scope_label}", showlegend=False)
        volume_fig.update_xaxes(type="category")

    if volatility_df.empty:
        volatility_fig = _empty_figure(f"No volatility data for {scope_label} yet.")
    else:
        volatility_fig = go.Figure(
            go.Bar(
                x=volatility_df["symbol_display"],
                y=volatility_df["range_pct"],
                marker_color=SEQUENTIAL_BLUE,
                customdata=volatility_df["company"],
                hovertemplate="%{x} — %{customdata}<br>Range: %{y:.2f}%<extra></extra>",
            )
        )
        volatility_fig.update_layout(title=f"Top 10 by intraday range % — {scope_label}", showlegend=False)
        volatility_fig.update_xaxes(type="category")

    # Region Performance only makes sense comparing regions against each
    # other, so it's only rendered on the Global tab.
    if region_tab != "Global":
        region_growth_content = _empty_state(f"Switch to the Global tab to compare regions (you're on {scope_label}).", icon="\U0001f30d")
    else:
        # region_tab == "Global" here, so latest_tab (queried with region=None
        # above) already *is* the all-regions latest snapshot -- no need to
        # query again.
        latest_all = latest_tab
        region_perf = analyze.region_growth(latest_all) if not latest_all.empty else latest_all
        if region_perf.empty:
            region_growth_content = _empty_state("No region data yet.")
        else:
            region_fig = go.Figure(
                go.Bar(
                    x=region_perf["region"],
                    y=region_perf["change_pct"],
                    marker_color=_sign_colors(region_perf["change_pct"]),
                    hovertemplate="%{x}<br>Avg change: %{y:+.2f}%<extra></extra>",
                )
            )
            region_fig.update_layout(title="Average change % by region", showlegend=False)
            region_growth_content = dcc.Graph(figure=region_fig)

    # "Latest Data" is a top-20-upward-movers leaderboard, not a browse-all
    # table -- rank first and only pull sparkline history for those 20
    # symbols, instead of querying recent bars for all 485 just to discard
    # most of them.
    top_20 = latest_tab.sort_values("change_pct", ascending=False).head(20) if not latest_tab.empty else latest_tab

    if top_20.empty:
        quotes_with_extras = _with_company(top_20)
    else:
        if region:
            recent_bars = read_recent_bars(region=region, symbols=top_20["symbol"].tolist(), limit_per_symbol=15)
        else:
            recent_bars = pd.concat(
                [
                    read_recent_bars(region=r, symbols=grp["symbol"].tolist(), limit_per_symbol=15)
                    for r, grp in top_20.groupby("region")
                ],
                ignore_index=True,
            )
        quotes_with_extras = _with_sparkline(_with_company(top_20), recent_bars)

    if quotes_with_extras.empty:
        quotes_table = _empty_state(
            "No stored data yet for this tab — run scripts/backfill_db.py to populate the database."
        )
    else:
        display_cols = ["symbol_display", "company", "trend", "timestamp", "close", "change", "change_pct", "volume"]
        display_cols = [c for c in display_cols if c in quotes_with_extras.columns]
        column_names = {"symbol_display": "Symbol", "trend": "Trend"}
        columns = [_column_def(c, column_names.get(c, c.replace("_", " ").title())) for c in display_cols]
        # "symbol" (the raw, unsuffixed value) rides along in `data` even
        # though it's not in `columns`/on screen -- show_company_news needs
        # the real ticker, not the display-only "700.HK"-style label.
        data_cols = display_cols + (["symbol"] if "symbol" not in display_cols else [])
        quotes_table = _dark_table(
            "quotes-table", quotes_with_extras[data_cols].to_dict("records"), columns, centered_cols=("trend",)
        )

    if gainers.empty:
        gainers_table = _empty_state("No gainers to show yet.", icon="\U0001f4ca")
    else:
        gainers_cols = ["region", "symbol_display", "company", "open", "high", "low", "close", "volume", "change_pct"]
        gainers_cols = [c for c in gainers_cols if c in gainers.columns]
        gainers_names = {"symbol_display": "Symbol"}
        gainers_table = _dark_table(
            "top-gainers-table",
            gainers[gainers_cols].to_dict("records"),
            [_column_def(c, gainers_names.get(c, c.replace("_", " ").title())) for c in gainers_cols],
        )

    if region_tab == "Global":
        symbol_options = [{"label": o["label"], "value": o["value"]} for o in SYMBOL_OPTIONS]
    else:
        symbol_options = [{"label": o["label"], "value": o["value"]} for o in SYMBOL_OPTIONS if o["region"] == region_tab]

    return (
        hero,
        f"Latest Snapshot — {scope_label}",
        change_fig,
        f"Latest Data — {scope_label}",
        quotes_table,
        f"Top Gainers — {scope_label}",
        gainers_table,
        f"Top by Volume — {scope_label}",
        volume_fig,
        f"Top by Volatility (High-Low Range %) — {scope_label}",
        volatility_fig,
        region_growth_content,
        symbol_options,
        top_gainer_symbol,
    )


@app.callback(
    Output("news-store", "data"),
    Input("region-tabs", "id"),
)
def load_top_stories(_id):
    """Fetched once, on initial page load only (Input is a static id/property
    so this never re-fires on tab clicks) -- yfinance is free/unauthenticated
    so this is not subject to the same quota rules as the market-data
    providers, but it's still a live call and shouldn't re-fire on every
    click. Pulls one set of 4 stories per region (Global + US + Europe +
    Asia), each from that region's own index, and stores all 4 in one shot;
    a separate display callback below picks which set to show based on the
    active tab, with no extra fetch on tab clicks. Yahoo tags the same
    major-market story to multiple related index tickers, so Global/US in
    particular can otherwise return near-identical sets -- fetch extra
    candidates per region and drop any story (by link) already claimed by an
    earlier region."""
    if IS_SNAPSHOT:
        return {}
    stories_by_tab = {}
    seen_links = set()
    for tab in REGION_TABS:
        try:
            candidates = news.get_top_stories(8, index=news.REGION_INDEX[tab])
        except Exception:
            candidates = []

        unique = []
        for story in candidates:
            link = story.get("link")
            if link and link in seen_links:
                continue
            unique.append(story)
            if link:
                seen_links.add(link)
            if len(unique) == 4:
                break

        stories_by_tab[tab] = unique
    return stories_by_tab


@app.callback(
    Output("top-stories-title", "children"),
    Output("top-stories", "children"),
    Input("region-tabs", "value"),
    Input("news-store", "data"),
)
def show_top_stories(region_tab, stories_by_tab):
    title = f"Top Stories — {region_tab}"
    if IS_SNAPSHOT:
        return title, [_empty_state("News is switched off in the static demo.", icon="\U0001f4f0")]
    if not stories_by_tab:
        return title, [_empty_state("Loading stories…", icon="\U0001f4f0")]

    stories = stories_by_tab.get(region_tab) or []
    story_items = _news_list(stories) if stories else [_empty_state("No stories available right now.", icon="\U0001f4f0")]
    return title, story_items


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

    if IS_SNAPSHOT:
        return _empty_state("Company news is switched off in the static demo.", icon="\U0001f4f0")

    try:
        stories = news.get_company_news(_yahoo_ticker(symbol), count=5)
    except Exception as e:
        return html.P(f"Could not load news for {symbol}: {e}")

    if not stories:
        return _empty_state(f"No news found for {symbol}.", icon="\U0001f4f0")

    return html.Div(
        [
            html.P(f"News for {symbol}", className="section-title", style={"marginTop": "18px"}),
            html.Ul(_news_list(stories), className="news-grid"),
        ]
    )


@app.callback(
    Output("trend-chart", "figure"),
    Input("trend-symbol-selector", "value"),
)
def update_trend_chart(symbol: str | None):
    if not symbol:
        return _empty_figure("Search and select a symbol above to see its trend.")

    region = SYMBOL_REGION_CODE.get(symbol)
    history = read_symbol_history(region, symbol) if region else pd.DataFrame()

    if history.empty:
        return _empty_figure(f"No stored data for {symbol} yet — run scripts/backfill_db.py to populate it.")

    customdata = history[["open", "high", "low", "change_pct"]].to_numpy()
    fig = go.Figure(
        go.Scatter(
            x=history["timestamp"],
            y=history["close"],
            mode="lines",
            line=dict(color=SEQUENTIAL_BLUE, width=2, shape="spline"),
            fill="tozeroy",
            fillcolor="rgba(57, 135, 229, 0.14)",
            customdata=customdata,
            hovertemplate=(
                "%{x|%b %d, %Y %H:%M}<br>"
                "Close: %{y:.2f}<br>"
                "Open: %{customdata[0]:.2f}  High: %{customdata[1]:.2f}  Low: %{customdata[2]:.2f}<br>"
                "Change: %{customdata[3]:+.2f}%<extra></extra>"
            ),
        )
    )
    fig.update_layout(title=f"{symbol} — closing price (daily)", showlegend=False)
    fig.update_yaxes(rangemode="tozero")
    return fig


if __name__ == "__main__":
    debug = os.environ.get("DASHBOARD_DEBUG", "false").lower() == "true"
    app.run(debug=debug)
