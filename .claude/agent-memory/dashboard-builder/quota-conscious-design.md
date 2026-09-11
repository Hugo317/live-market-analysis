---
name: quota-conscious-design
description: When a single user action needs both "fetch fresh data" and "display it," read the freshly-persisted DB row instead of calling the provider API a second time — critical for EODHD's 20/day cap.
metadata:
  type: feedback
---

This project's free-tier quotas are tight enough (EODHD 20 calls/day total, unbatched) that any
UI action which could plausibly call the same provider endpoint twice is a real bug, not a style
nitpick.

Concrete case: the Historical Trend dropdown callback needs to (a) persist newly-fetched bars via
`fetch_raw.fetch_symbol_historical(...)` and (b) chart them. The naive approach — call
`fetch_symbol_historical` for persistence, then separately call `analyze.get_symbol_history` to
get chart data — hits the same provider's historical endpoint twice per dropdown selection,
silently doubling EODHD quota burn for every EU lookup.

Fix: after `fetch_symbol_historical` + `merge_quotes()`/`clean()`/`upsert_quotes()` land the data
in the DB, read the chart data back out of the DB (`read_quotes(region=...)` filtered to the
symbol) instead of calling `analyze.get_symbol_history` again. One user action → one provider API
call. Apply this pattern any time a callback both fetches-to-persist and displays in the same
trigger.

**Why:** EODHD's cap is small enough (20/day) that doubling any single action's call count is
user-visible within a day of normal use, and the whole point of the fetch_raw split
(`fetch_bulk_historical` vs `fetch_symbol_historical`) was to make each provider call intentional
and countable.

**How to apply:** Before wiring a callback that both fetches fresh data and renders it, check
whether the render step could instead read from the DB/cache that the fetch step just populated,
rather than issuing its own independent API call.
