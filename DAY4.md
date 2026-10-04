# Day 4 — Model-driven MCP review

Day 3 let you call tools manually in Inspector. Day 4 gives the LLM those tools,
lets it choose their sequence, returns each tool result to it, and asks for a
structured review proposal. Python checks the proposal before accepting it.
Inspector is optional; the agent starts its own stdio MCP subprocess.

## Windows setup

1. Extract this ZIP into a new `tripledger-day4` folder. Open PowerShell **inside
   the folder containing `app`, `agent`, `requirements.txt` and this file**.
2. Copy your working Day 3 `.env` into this folder. Keep the same working custom
   chat and embedding settings. Keep `EMBEDDING_DIMENSIONS=` blank. Do not copy
   the old `.venv`; create a new one:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m evals.validate_fixtures
```

If mypy remains blocked by your corporate Application Control policy, use an
approved environment; it is not required to run the agent.

## Run the first real review

Stop your previous Day 2/3 mock process with Ctrl+C so its ports are free.
Day 4 needs the new evaluation employees and transactions, not just the old seed.
In terminal 1, start the four services from this folder:

```powershell
.\.venv\Scripts\python.exe -m mock_systems.run
```

It now defaults to `mock_systems/seed/day4-data.json`, which preserves all old
records and adds the 25 evaluation scenarios. In terminal 2, from the same folder:

```powershell
.\.venv\Scripts\python.exe -m app.cli llm-smoke
.\.venv\Scripts\python.exe -m app.day4 --report examples/clean-report.json
```

The smoke call checks text generation. The review additionally requires your
custom gateway/model to support OpenAI-style `tools` and `tool_calls`. This has
not been tested against your corporate gateway here. No embedding calls are
needed for Day 4: policy documents are loaded directly from MCP resources.

For the clean report, the target result is `status: complete`, `auto_approve`,
EUR 20.00 reimbursable, EUR 0.00 disallowed, one matched taxi line, and no findings.
That is the expected fixture outcome, not a promise about an untested model.
`queued: false` is normal without `--queue`.

The command prints an `output_directory` containing:

- `result.json`: accepted proposal or incomplete-run status.
- `trace.json`: redacted report, policy snapshot, model responses, usage, tool
  arguments/results and validation feedback. It does not request hidden reasoning.

Do not paste your `.env` or API keys when sharing a failure. The useful information
is the status/reason, validation feedback and relevant tool error codes.

## Check pagination

```powershell
.\.venv\Scripts\python.exe -m app.day4 --report evals/reports/EVAL-23.json
```

This contains 21 EUR 1 taxi lines, with 21 transactions: the card API returns 20
on page one and one on page two. Expected outcome is EUR 21.00 reimbursable and
zero disallowed. The trace should show an initial `list_card_transactions` call
and another with `cursor: "20"`, using the same employee and date range.

## Optional review queue and batch

To save a complete validated proposal to the **mock** queue:

```powershell
.\.venv\Scripts\python.exe -m app.day4 --report examples/clean-report.json --queue
```

The LLM cannot call `save_decision` itself; the host calls it after validation and
only when `--queue` is supplied. Incomplete runs are never queued. This does not
send messages or execute payments. The ledger rejects a different payload for an
already queued report ID; rerunning a review changes metadata, so a subsequent
queue attempt can return a conflict. Use the default unqueued mode for iteration.

The following runs **25 real LLM reviews**, each with up to 12 model rounds:

```powershell
.\.venv\Scripts\python.exe -m app.day4 --batch evals/reports
```

The batch validates each report and continues past invalid report files. It does
not score accuracy. `evals/labels.json` holds expected outcomes and rule coverage;
labels are never sent to the model. Scoring and benchmark reporting come later.

## Bounds and failure behavior

Each review permits at most 12 model rounds, 12 tool calls per round and 48 tool
calls overall. The third identical call returns `REPEATED_TOOL_CALL` instead of
running again. The model may group calls and choose a different order on each run.
The host only preloads policy and tool definitions; it does not prescribe a fixed
business-tool sequence. The context limit is 150,000 serialized characters, not
provider tokens. No automatic summarization discards evidence.

The host checks report identity, required successful reads, attached receipts,
first-page/date-range coverage, outstanding cursors, returned matching candidates,
unique transaction assignment and compute totals. Foreign report amounts must
have matching FX tool results. Auto-approval additionally requires no blocking or
query findings, matched lines, sufficient confidence, no duplicate candidates and
a total below the policy ceiling. Full independent verification of model-selected
caps, findings and every policy rule is **not yet implemented**.

`status: incomplete` produces a manager-review placeholder with confidence zero,
null totals and a reason such as `STEP_BUDGET_EXHAUSTED`, `MODEL_API_ERROR` or
`CONTEXT_LIMIT`. This placeholder is intentionally **not** a valid final Decision
and cannot be queued. Inspect the trace to resolve missing evidence or provider
support. A completed decision's absent provider token counts remain null.

For an API 400 during review after smoke succeeds, check whether your model accepts
native function tools and your configured temperature/request fields. A very low
`max_completion_tokens` in `LLM_EXTRA_BODY_JSON` can truncate tool arguments or
final JSON. Do not assume that the text smoke test proves function-call support.

## Fixture inventory

| Reports | Purpose |
|---|---|
| 01–02 | Clean taxi; hotel below cap |
| 03–09 | Date, receipt, hotel, meal, cabin, alcohol and prohibited MCC rules |
| 10–11 | Within-report and settled-history duplicates |
| 12–13 | Late submission and approval ceiling |
| 14–17 | Director cabin exception, long-flight exception, client dinner, hotel boundary |
| 18–19 | Receipt at EUR 25; hotel cap exceeded by EUR 0.01 |
| 20–22 | Instructions embedded in description, merchant and receipt text |
| 23–24 | Two-page clean report; two-page report with a missing required receipt |
| 25 | No matching card transaction |

The fixture seed adds 25 employees, 25 trips, 65 card transactions and one settled
line. Receipts remain synthetic JSON; image extraction is Day 5. The demo MCC
resource now includes airline code 4511 and resource version `2026-Q2-demo-2`.
Matching returns the best three candidates per line with an omitted-candidate
count to bound context; ambiguous or omitted alternatives need adjudication.
The injected fixtures test future model behavior; their presence alone does not
prove prompt-injection resistance.

## Code map

| File | Responsibility |
|---|---|
| `app/day4.py` | CLI, custom API client, one report/batch, result files |
| `app/intake.py` | Report validation; email/phone/card-like string redaction |
| `agent/loop.py` | MCP discovery, model rounds, dispatch, budgets, trace |
| `agent/prompts.py` | Behavioral instructions; policy numbers stay in resources |
| `agent/contracts.py` | Inline MCP JSON schema references for function tools |
| `agent/memory.py` | Bounded serialized context |
| `app/assembler.py` | Minimal Day 4 acceptance checks |
| `evals/build_day4_fixtures.py` | Reproduce labelled synthetic cases and backend seed |
| `tests/test_day4.py` | Scripted model responses with real MCP/HTTP mocks |

Redaction is a conservative demo heuristic, not comprehensive PII detection.
Use synthetic records. Traces contain report and tool content after redaction.
Day 5 adds receipt extraction and fuller independent verification; Day 6 adds
scoring/benchmarks. Day 4 proposes reviews, not production reimbursement decisions.
