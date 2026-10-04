# TripLedger Day 3 — MCP tools, resources and matching

This project includes Days 1, 2 and 3. Day 3 exposes existing integrations and
calculations through a real MCP stdio server. There is no autonomous model loop yet.
Your custom LLM and embedding smoke commands still work; Day 3 does not call them.

## 1. Install and preserve your working configuration

Extract to a new folder. Copy your working `.env` from Day 2 into this folder.
Do not overwrite it with `.env.example` or share its keys. Keep your working
`EMBEDDING_DIMENSIONS=` blank. Recreate the environment rather than copying `.venv`.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

The new dependency is the official MCP Python SDK v1 (`mcp>=1.30,<2`) plus JSON
Schema validation. `requirements-lock.txt` records exact tested versions.
Node.js/npm is needed only for MCP Inspector, not the Python server or smoke test.

## 2. Terminal 1 — keep the mock services running

```powershell
.\.venv\Scripts\python.exe -m mock_systems.run
```

This starts the same card, travel, HR and ledger services on ports 8011–8014.
If your Day 2 services already use those ports, stop that runner first or use it
instead of starting another copy. See DAY2.md for configurable ports.

## 3. Terminal 2 — verify the complete MCP connection

```powershell
.\.venv\Scripts\python.exe -m app.day3
```

This command starts the MCP subprocess, initializes the protocol and checks:

- Exactly 9 tools, 3 resources and 1 prompt are discoverable.
- All resources can be read and the prompt can be retrieved.
- Every tool can be called, including queue storage of the illustrative decision.
- Both transaction pages produce 30 records overall.
- `UBER *TRIP HELP.UBER.CO` pairs with `UBER BV AMSTERDAM`.
- An invalid extra argument produces the documented error envelope.
- The Milan allowance read from the resource produces EUR 52 hotel excess.

The default FX check uses EUR→EUR with a rate of 1, avoiding an external dependency
for the protocol test. To exercise the public historical USD/EUR API through MCP:

```powershell
.\.venv\Scripts\python.exe -m app.day3 --live-fx
```

The smoke test writes the same illustrative decision used on Day 2, not a newly
reviewed report. Identical queue writes are idempotent. If you previously changed
that report's queued decision, the mock correctly returns a conflict.

## 4. Open MCP Inspector

From the project folder, with the mock services still running:

```powershell
npx --yes @modelcontextprotocol/inspector@2.9.0 .\.venv\Scripts\python.exe run_mcp.py
```

Open the local Inspector URL printed by that command. Keep its session token
private. Select/connect to the stdio server, then use the Tools, Resources and
Prompts panels. If entering settings manually, use:

- Transport: `STDIO`
- Command: full path to this project's `.venv\Scripts\python.exe`
- Arguments: full path to `run_mcp.py` in this project
- Working directory: this extracted project folder

Do not run the MCP server in Terminal 1 in place of the mocks. Inspector starts
its own server subprocess. Running `python -m mcp_server.server` alone looks idle
because it is waiting for protocol messages on stdin. It is not an HTTP endpoint
and cannot be tested by opening a browser URL or using Postman directly.

The `run_mcp.py` launcher avoids Inspector argument parsing conflicts with Python’s `-m` flag.

CLI discovery is also available:

```powershell
npx --yes @modelcontextprotocol/inspector@2.9.0 --cli .\.venv\Scripts\python.exe run_mcp.py --method tools/list
npx --yes @modelcontextprotocol/inspector@2.9.0 --cli .\.venv\Scripts\python.exe run_mcp.py --method resources/list
npx --yes @modelcontextprotocol/inspector@2.9.0 --cli .\.venv\Scripts\python.exe run_mcp.py --method prompts/list
```

If your corporate machine blocks Node or npm packages, use an approved Node/npm
installation. Python's `app.day3` remains available for protocol checks; it is not
a replacement claim that the Inspector requirement passed locally.

## The nine tools

| Tool | Kind | Arguments / behavior |
|---|---|---|
| `get_employee` | Fetch | `employee_id` |
| `get_trip` | Fetch | `trip_id` |
| `list_card_transactions` | Fetch | `employee_id`, `from`, `to`, optional `cursor`; one page at a time |
| `list_settled_lines` | Fetch | `employee_id`, `months` from 1 through 12 |
| `read_receipt` | Fetch | `file_path`; synthetic JSON receipt fixtures for Day 3 |
| `fx_convert` | Compute | `amount`, `from_ccy`, `to_ccy`, `on_date` |
| `compute_totals` | Compute | `lines`, `caps`, `base_currency` |
| `match_transactions` | Compute | `lines`, `transactions`; candidate scores, not final matches |
| `save_decision` | Write | Full Decision object as arguments; review queue only |

Every input contract rejects unknown fields. JSON Schema is applied before
Pydantic's semantic checks. The SDK's default input validator is replaced by this
explicit validation so malformed arguments return a consistent safe envelope.
The tool is not executed when validation fails. No supplied input values are
included in error text.

Successful result (also in MCP `structuredContent`):

```json
{"ok": true, "data": {"grade": "Consultant"}}
```

Error result:

```json
{
  "ok": false,
  "error": {
    "code": "INVALID_ARGUMENTS",
    "message": "Arguments do not match the published schema.",
    "retryable": false,
    "hint": "Check required fields, types, date ranges and constraints; values are not logged."
  }
}
```

Expected domain errors are normal MCP results (`isError=false`) with `ok=false`
inside the envelope. This lets a future agent reason about the failure. Clients
must check `ok` rather than assuming every protocol-success response contains data.
Monetary values remain decimal strings.

## Inspector examples

Use the tool input form, or paste the corresponding JSON:

**Get employee**

```json
{"employee_id":"EMP-2231"}
```

**First card page**

```json
{"employee_id":"EMP-2231","from":"2026-04-07","to":"2026-04-14"}
```

For page two, add `"cursor":"20"`.

**Read synthetic receipt**

```json
{"file_path":"receipts/L1.json"}
```

Only small JSON receipt fixtures inside the configured receipt directory are
supported now. Absolute paths, traversal and symlink escapes are rejected. A JPEG,
PNG or PDF returns `IMAGE_EXTRACTION_DEFERRED`; it is not falsely reported as read.
Real multimodal extraction and low-confidence vision handling remain Day 5 work.

**Match transactions** — also provided in `examples/match-request.json`:

```json
{
  "lines":[{"line_id":"L2","date":"2026-04-09","merchant":"UBER *TRIP HELP.UBER.CO","amount":"38.40","currency":"EUR","category":"taxi"}],
  "transactions":[{"txn_id":"TXN-00-022","posted_date":"2026-04-09","merchant_raw":"UBER BV AMSTERDAM","amount":"38.40","currency":"EUR"}]
}
```

Expected top pair: `L2` → `TXN-00-022`, score `1.0`. Multiple candidate pairs are
preserved for later adjudication. An unmatched ID means no candidate passed the
matching heuristic, not proof that a payment is absent.

**Invalid input**: add `"unexpected":true` to the employee request. Expect
`INVALID_ARGUMENTS`, without an HTTP fetch.

**Queue write**: paste the complete `examples/decision.json` object as the input
for `save_decision`, without wrapping it in a `decision` property.

## Three resources and one prompt

| Resource URI | Local source |
|---|---|
| `tripledger://policy/expense-policy` | `mcp_server/resources/expense-policy.md` |
| `tripledger://policy/per-diem` | `mcp_server/resources/per-diem.json` |
| `tripledger://reference/mcc-codes` | `mcp_server/resources/mcc-codes.json` |

All resources have version `2026-Q2-demo-1` and are read from disk at request time.
Rules R-01 through R-10 follow the assignment. The city/grade allowance values and
MCC teaching table are explicitly labelled demo choices where screenshots did
not provide complete data. The policy documents the EUR 2500 boundary ambiguity:
FR-18's stricter 'below ceiling' gate is used for that boundary in future work.

Prompt `review_expense_report` takes `report_id`. It instructs the future agent to
read policy, collect evidence, use calculations, and write only to the queue. It
does not embed allowance values or create an autonomous agent.

To demonstrate resource changes, read the Milan Consultant allowance (120), call
`compute_totals` for EUR 412 / 3 nights, then change the allowance to 140 and bump
the resource version. Read it again and pass the new cap to the tool. Excess
changes from EUR 52 to zero without editing code or restarting. The calculator
uses the **supplied** cap; an earlier tool input does not update automatically.

## Matching algorithm and limitations

Merchant strings are case-normalized, Unicode-normalized, punctuation-stripped,
and legal suffixes removed. Uber-prefixed variants have a specific normalization.
Candidate score weights: merchant similarity 55%, amount proximity 30%, date
proximity 15%. Different currencies are never matched without explicit conversion.
Date gap must be at most 3 days. Amount tolerance is 20% for taxi/meals and 2% for
other categories; merchant similarity must be at least 0.45 and score at least 0.70.
These are matching heuristics, not reimbursement policy or calibrated confidence.
Every monetary delta is computed using Decimal. Similarity scores use floats.
Thresholds have not been tuned against the later 25-report evaluation set.

## Tests and verification

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy
```

See `RESULTS-DAY3.md` for the actual delivered results. Your previous Windows mypy
App Control block is a local environment issue; use your approved development
setup rather than disabling the policy.

New implementation: `mcp_server/server.py`, `dispatch.py`, `tool_contracts.py`,
`matching.py`, and three resource files. `integrations/mcp_client.py` is a small
stdio probe used by tests and `app/day3.py`; model orchestration belongs to Day 4.
Day 3 does not pass expense reports to the custom LLM or embedding API.

Official references:
- https://py.sdk.modelcontextprotocol.io/v1/
- https://github.com/modelcontextprotocol/inspector
