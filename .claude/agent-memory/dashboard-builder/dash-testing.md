---
name: dash-testing
description: Correct payload shape for exercising Dash callbacks via /_dash-update-component without a browser, and how to test guard branches without triggering live API calls.
metadata:
  type: feedback
---

When testing `app.py` callbacks with curl against `/_dash-update-component` (Dash callbacks using
`dash.ctx` can't be called as plain Python functions — raises `MissingCallbackContextException`):

- `output` must be the literal Dash-encoded string `"..id1.prop1...id2.prop2.."` (double dots
  around each `id.prop`, triple dots between entries). Getting this wrong produces a `KeyError:
  Callback function not found for output '...'` 500 — that's a malformed test payload, not an app
  bug. Don't mistake it for one.
- `outputs` must mirror `output` in list form: `[{"id":..., "property":...}, ...]` for multi-output
  callbacks. For a *single*-output callback, `outputs` must be a bare object, not a
  single-element list, or Dash raises a wildcard-multi-output error even though the callback logic
  is fine (noted in project CLAUDE.md too).
- `inputs` is a list of `{"id", "property", "value"}`; `changedPropIds` should list which
  `id.property` changed (e.g. `["trend-symbol-selector.value"]`).
- To verify a guard clause (e.g. "unknown dropdown value must not crash") without spending API
  quota, pick input values that hit the guard before any `fetch_raw`/`analyze` call — e.g. an
  unrecognized symbol string or `null`/no-selection. Confirmed working pattern: returns 200 with a
  safely-defaulted figure/status, and the server log shows no outbound API call attempted.
- Always boot the dev server backgrounded with a short `sleep` before curling, then `pkill -f
  "live_market_analysis.dashboard.app"` afterward — never leave it running.
