# Dashboard Builder Memory

- [Dash testing endpoint payload shape](dash-testing.md) — correct `output`/`outputs` format for `/_dash-update-component`, and how to test guard logic without hitting live APIs.
- [Historical-only pipeline migration](historical-pipeline-migration.md) — schema shift from live-quote to multi-row-per-symbol historical bars, and the `latest_per_symbol` convention.
- [Quota-conscious callback design](quota-conscious-design.md) — avoid double-calling a provider API in a single user action (e.g. fetch+chart), especially for EODHD's 20/day cap.
