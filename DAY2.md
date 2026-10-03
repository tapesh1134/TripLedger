# TripLedger Day 2 — Integration

This ZIP contains **Day 1 + Day 2**. Keep your working Day 1 folder as a backup.
The custom LLM and embedding adapters remain available, but Day 2 commands do not
call them. Copy your working `.env` into this new folder; do not overwrite it
with the example file. Your working blank `EMBEDDING_DIMENSIONS=` stays blank.

## Setup on Windows

Extract the ZIP, open the `tripledger-day2` folder, and create a fresh environment:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

Copy your existing `.env` into this folder. All Day 2 settings have usable defaults,
so no changes to your working model configuration are required. The new
`.env.example` documents optional port, URL, delay and FX cache settings.
Dependencies now include HTTPX SOCKS support for environments using such proxies.
No PostgreSQL, Docker, API key, or model is needed to run the mock services.

## Terminal 1 — start the four services

```powershell
.\.venv\Scripts\python.exe -m mock_systems.run
```

Leave this terminal running. Ctrl+C stops all services.

| Mock system | Address | Purpose |
|---|---|---|
| Card | http://127.0.0.1:8011 | Corporate transactions, 20 per page |
| Travel | http://127.0.0.1:8012 | Booked trips, flights, hotel nights |
| HR | http://127.0.0.1:8013 | Employee grade and cost centre |
| Ledger | http://127.0.0.1:8014 | Settled lines and review queue |

Each provides `GET /health`. The servers bind to loopback only and are local demo
services, not production deployment servers. They share a runner process but use
four independent HTTP servers/ports. There is no Swagger dependency.

## Terminal 2 — fetch real HTTP data from the local mocks

```powershell
.\.venv\Scripts\python.exe -m app.day2 demo
```

Expected highlights:

- Employee `EMP-2231`, trip `TRP-8890` (Milan, April 9–12, 2026).
- `first_page_count: 20` and `first_page_next_cursor: "20"`.
- `all_pages_count: 30` after following the cursor.
- `hotel_found_after_pagination: true`: the sample EUR 412 hotel transaction is
  deliberately on page two.
- One settled taxi line that can support duplicate detection in later days.

This is data retrieval, not autonomous reconciliation or a compliance decision.
The card search uses the trip range plus two days on either side.

## Exercise the failure/retry path

```powershell
.\.venv\Scripts\python.exe -m app.day2 retry-demo
```

The card service fails every tenth transaction request with HTTP 503. This is a
repeatable 1-in-10 failure schedule, rather than random failure. The adapter
retries HTTP 429, 5xx, and transport timeouts up to three times, with exponential
backoff and jitter. Retry metadata is logged without request bodies or keys.
The demo should finish with 12 successful calls and at least one retry. Travel
requests have a default 150 ms delay. Set `MOCK_CARD_FAIL_EVERY=0` to disable
injected failures; keep the default when demonstrating retries.

## Convert using the real historical FX API

```powershell
.\.venv\Scripts\python.exe -m app.day2 fx --amount 100 --from-ccy USD --to-ccy EUR --date 2026-04-09
```

The result includes converted `amount`, exact decimal `rate`, `requested_date`,
`rate_date`, `source`, `calc_id`, and `cached`. Run it again: `cached` should be
`true`, with the same rate and monetary result. The public FX request sends only
the currency pair and date, not the expense report, employee or LLM API key.

Implementation uses the documented [Frankfurter v1 historical endpoint](https://frankfurter.dev/v1/).
V1 is deprecated in favour of v2 but remains operational; this adapter uses its
simple stable response shape. A future v2 migration requires adapting the parser,
not merely changing the URL.

- No `latest` endpoint and no invented or approximate fallback rate.
- Conversion uses Decimal and `ROUND_HALF_UP` to two decimal places, consistent
  with Day 1's EUR demonstration. Other minor-unit conventions remain out of scope.
- Working-day data may carry an earlier effective date; both dates are preserved.
  A future rate or one older than seven days is rejected.
- Only completed past dates are accepted to avoid caching changing intraday rates.
- SQLite cache keys include provider, currency pair and requested date. It is in
  `runtime/fx-cache.sqlite3`. Amounts are recomputed from the cached rate.
- Missing/invalid rates or outages return a structured error; no conversion is
  silently fabricated. The agent's escalation behavior comes in later days.
- FX respects environment proxy settings; the local mock client bypasses proxies
  so localhost requests stay local. TLS verification remains enabled.

## Persist an illustrative decision in the review queue

```powershell
.\.venv\Scripts\python.exe -m app.day2 queue-example
Invoke-RestMethod http://127.0.0.1:8014/review-queue
```

This posts the existing **illustrative Day 1 fixture**, not an agent-generated
review. The queue is stored in `runtime/review-queue.sqlite3` and survives restarts.
Posting an identical decision again returns the same ID without duplicating it.
A changed decision with the same report ID returns HTTP 409. Writes are schema
validated. There are no payment/payroll endpoints. Full policy verification of a
queued decision belongs to Day 5, not this mock storage API.

## Endpoints for Postman

| Method | Port | Path |
|---|---:|---|
| GET | 8011 | `/transactions?employee_id=EMP-2231&from=2026-04-07&to=2026-04-14` |
| GET | 8011 | `/transactions?employee_id=EMP-2231&from=2026-04-07&to=2026-04-14&cursor=20` |
| GET | 8011 | `/transactions/TXN-00-021` |
| GET | 8012 | `/trips/TRP-8890` |
| GET | 8012 | `/trips?employee_id=EMP-2231` |
| GET | 8013 | `/employees/EMP-2231` |
| GET | 8014 | `/settled-lines?employee_id=EMP-2231&months=12` |
| GET / POST | 8014 | `/review-queue` |

The mock ledger uses a fixed `as_of=2026-04-18` fixture clock, so the seeded history
remains demonstrable when run later. An optional `as_of=YYYY-MM-DD` query changes
that clock explicitly. The lookback filters expense dates and excludes records
settled after the as-of date.

## Synthetic fixtures and tests

Fixtures are included in `mock_systems/seed/data.json`: 30 employees, 20 trips,
600 card transactions (30 per trip employee), and 21 settled lines. Ten of the
employees have no trip. Only `card_last4` is generated; no full card number is
created or stored. Names and all records are synthetic. Regenerate with:

```powershell
.\.venv\Scripts\python.exe -m mock_systems.seed_data
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy
```

Tests start isolated servers on temporary ports and temporary SQLite databases.
FX unit tests use explicit fake responses; these are not cached as live data or
included as live-rate evidence. Keep the known corporate mypy policy block marked
as blocked if it still occurs on your laptop; it does not prevent Day 2 runtime.

See `RESULTS-DAY2.md` for delivered verification and any live-FX limitation.

## Reading the code

- `mock_systems/seed_data.py`: builds the fake records reproducibly.
- `mock_systems/service.py`: endpoint behavior for all four service roles.
- `mock_systems/run.py`: starts/stops their four HTTP listeners.
- `mcp_server/backend.py`: server-side adapters and bounded retries.
- `mcp_server/fx.py`: historical-rate validation, caching and conversion.
- `app/day2.py`: runnable integration demos.
- `tests/test_day2.py`: integration, cache, pagination and failure cases.

Original `card_feed.py`, `travel.py`, `hr.py`, `ledger.py` files point to the shared
service implementation; this avoids four duplicated HTTP servers. MCP transport,
policy resources, matching and the autonomous loop remain Day 3+ work.
