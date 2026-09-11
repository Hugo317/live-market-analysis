---
name: redesign-verification-2026-09-11
description: QA verification of major visual redesign (dark theme, hero cards, sparklines); all code paths working correctly
metadata:
  type: project
---

## Redesign Verification Summary (2026-09-11)

### Verified Areas — ALL PASS

**1. Module Imports & Dash App Boot — PASS**
- App imports cleanly without errors
- Dash app object builds successfully (`app.layout` exists)
- Plotly `market_dark` template registers and becomes default
- Symbol caching via `symbols.py` is offline-safe (Wikipedia .cache/ hit)
- All 4 callbacks register without errors

**2. New Helper Functions — PASS**
- `_sparkline_svg`: Builds valid SVG with base64 encoding; handles edge cases (empty list → "", single value → "")
- `_sign_colors`: Correct mapping (positive/zero → GOOD, negative → CRITICAL)
- `_empty_figure`: Proper Plotly structure with annotation layer
- `_stat_card`: Renders with correct HTML classes and tone modifiers
- `_with_sparkline`: Correctly groups history by (region, symbol); adds "trend" markdown-image column
- `_dark_table`: Works with `markdown_options={"html": True}` (valid Dash 4.4.1 option for markdown cell HTML rendering)

**3. Callback Wiring (Dynamic Quotes Table) — PASS**
- `quotes-table-wrapper` div exists in initial layout
- `quotes-table` component created dynamically in `update_dashboard` callback with consistent ID
- `show_company_news` callback depends on `quotes-table` with proper guards (`if not active_cell or not table_data: return None`)
- Pattern is valid: component created by first callback before dependent callback fires on user interaction
- No "nonexistent object" Dash errors

**4. Dashboard Dev Server Boot — PASS**
- Server starts without errors
- HTTP responds with 200 status on port 8050

**5. Analyze Functions — PASS**
- `top_gainers()`, `top_losers()` sort by `change_pct` correctly
- `top_by_volume()` sorts by volume descending
- `with_volatility()` computes range_pct = (high - low) / close * 100 correctly
- `top_volatility()` returns top N by range_pct
- `region_growth()` averages change_pct by region, sorts descending
- All functions work on latest-per-symbol aggregated data

### Critical Observations

**No Bugs Found**

The redesign code is production-ready. No issues detected with:
- Division by zero (sparkline uses `span = (hi - lo) or 1.0`)
- DataFrame groupby key mismatches (consistent use of ["region", "symbol"])
- Column name errors
- Callback execution order
- Component ID lifecycle

**Design Tokens**
- All colors defined in app.py (#SURFACE, #ACCENT, #GOOD, #CRITICAL, etc.) are used in CSS
- app.py includes hand-synced comment: "mirrors assets/style.css — kept in sync by hand"
- CSS file exists and is 344 lines
- Color values match between Python and CSS

### Known Limitation (Not a Bug)

From prior verification on 2026-09-11:
- `/data/raw/*.json` files contain old format (list of quote objects)
- Code expects new dict-of-symbols format: `{"symbol": [bar, ...]}`
- `merge_quotes()` will fail if called against on-disk files
- Fix: Run `fetch_raw.fetch_bulk_historical()` to regenerate data files (requires live API calls)

This is not a code bug — the new code is correct, raw data files are just stale.

### Test Coverage

- Fixture tests verify all new functions with edge cases
- Dashboard callback graph loads without errors
- All analyze functions tested with fixture data
- Symbol loading confirmed offline-safe via cache
