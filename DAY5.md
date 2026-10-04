# Day 5 — Receipt extraction and independent verification

Day 4 let your custom model select MCP tools and propose a decision. Day 5 adds
PNG/JPEG receipt extraction and a verifier that checks evidence and policy facts
before accepting a proposal. It specifically fixes the EVAL-24 failure where a
blocked, guessed receipt path appeared in the final evidence list.

## Windows setup

Extract into a new folder and open PowerShell inside the directory containing
`app`, `agent`, and `requirements-dev.txt`. Copy your working Day 4 `.env` here.
Keep your existing custom URL, key, authentication settings and embedding settings.
Keep `HTTP_TIMEOUT_SECONDS=120`, which you used for the successful EVAL-24 retry.

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

Use Python 3.11 or later. Do not copy the old virtual environment. If your corporate
Application Control policy blocks mypy, use an approved environment; the app can
run independently of mypy.

Stop the old mock process with Ctrl+C. In terminal 1, from the new project folder:

```powershell
.\.venv\Scripts\python.exe -m mock_systems.run
```

In terminal 2, from that same project folder, repeat the case that exposed the bug:

```powershell
.\.venv\Scripts\python.exe -m app.day5 --report evals/reports/EVAL-24.json
```

Expected: `status: complete`, `manager_review`, EUR 45.00 reimbursable, EUR 0.00
disallowed, R-02 query on L21, and **no blocked receipt path in evidence**.
If the model invents a citation, it gets validation feedback and must correct it.
A model that cannot correct its answer within the budget returns incomplete.

Also check the hotel deduction:

```powershell
.\.venv\Scripts\python.exe -m app.day5 --report evals/reports/EVAL-05.json
```

Expected: manager review; EUR 360.00 reimbursable, EUR 52.00 disallowed, R-03.
The host verifies the EUR 120 nightly allowance and three booked nights, so the
model cannot raise the cap or omit the deduction.

## Enable image receipts

JSON receipts remain local and do not require a vision API. Add these lines to
your copied `.env` when you want to test PNG/JPEG extraction:

```dotenv
RECEIPT_VISION_ENABLED=true
VISION_MODEL=
```

Blank `VISION_MODEL` uses your working `LLM_MODEL=openai.gpt-5-mini` and the same
custom API URL, key, TLS/CA, timeout and authentication settings. If your gateway
requires a different image-capable model, put its approved model ID in
`VISION_MODEL`. Text and tool-call success do not establish image support; that
must be tested locally. Embeddings are not called by this flow.

Test just the included synthetic image first; no mock servers are needed for this
standalone extraction command:

```powershell
.\.venv\Scripts\python.exe -m app.receipt_smoke receipts/day5/sample-taxi.png
```

Expected extracted fields: merchant `Cab company 1`, date `2026-04-09`, currency
EUR, total `20.00`, tax `0.00`, and a model-reported confidence. The fixture is a
synthetic test receipt, not a real purchase or proof of payment.

Then run the complete report, keeping the mock servers running:

```powershell
.\.venv\Scripts\python.exe -m app.day5 --report examples/vision-report.json
```

Expected with successful consistent extraction: auto-approve EUR 20.00, zero
disallowed. Low confidence, conflicting fields or unavailable vision require
manager review with a receipt query. A provider failure does not generate made-up
receipt fields. Receipt-extraction failure can still produce a complete manager
review when other required evidence is available; review-model failure still
produces an incomplete placeholder with null totals.

## What the verifier checks

| Area | Day 5 check |
|---|---|
| Citations | Source/ref must belong to the report, policy snapshot or a successful tool result |
| Failed calls | Error/blocked-call references cannot support findings |
| Matching | Recompute candidates from original claim lines and fetched transactions; verify deltas |
| Receipts | Attached paths only; merchant, date, currency and amount consistency; confidence threshold |
| R-01/R-02 | Travel-date allowance and required receipts, even if the model omits findings |
| R-03/R-07 | Resource-backed hotel caps and prohibited-category deductions; reject invented caps |
| R-04/R-06 | Structured meal/alcohol facts; daily solo-meal aggregation; uncertain client allocation goes to review |
| R-05 | Booked cabin, grade and flight duration |
| R-08 | Exact normalized merchant/date/amount/currency duplicates, in report and fetched settled history |
| R-09/R-10 | Submission age and approval ceiling |
| Final decision | Required findings/severities, draft queries, currency/totals and auto-approval gates |

The current teaching policy specifies monetary deductions for R-03 and R-07.
Other violations require review; the system does not invent deduction formulas.
`audit_hold` is not defined by this policy and is rejected in favor of manager
review. `DATA-QUALITY` query findings describe unresolved transaction evidence.
At exactly EUR 2500, the stricter existing auto-approval gate requires review.

Policy values live in the three MCP resources, version `2026-Q2-demo-3`.
`per-diem.json` now includes structured `controls` that mirror the teaching policy.
When editing policy, keep the structured controls, narrative and version aligned;
Python does not interpret arbitrary policy prose as executable rules. If you use
`POLICY_RESOURCE_DIR`, point it to the Day 5 resource set including these controls.

## Structured meal and hotel facts

The report schema adds optional fields without breaking existing reports:

```json
{
  "attendee_count": 3,
  "is_client_dinner": true,
  "alcohol_amount": "0.00",
  "hotel_nights": null
}
```

These fields belong on each relevant line item, alongside its existing fields.
Meal fixtures 06, 08 and 16 include explicit meal facts. Older meal reports without
these facts require review; the host does not guess attendee counts or alcohol
amounts from prose. A single hotel line may use booked trip nights; multiple hotel
lines need per-line nights, and declared nights cannot exceed the booking. Unknown
allowances or ambiguous allocations require review.

The label file lists primary expected policy violations. Additional data-quality
queries may be needed, for example when an out-of-trip transaction is outside the
queried card range. The malicious receipt merchant in case 22 also triggers a
receipt-consistency query. This remains an evaluation corpus, not a scored model
accuracy benchmark.

## Files, bounds and privacy

Each run writes `result.json` and `trace.json` under the printed
`runtime/reviews/<run-id>` directory. Traces include successful tool citation IDs,
validation feedback, extracted receipt fields and vision usage metadata, but no
base64 image content. Images are decoded, orientation-corrected, stripped of
metadata and resized before sending to the configured provider. The visible
receipt pixels are sent to that provider when vision is enabled; local text
redaction does not remove sensitive text from images. Use the synthetic fixture.

Only PNG/JPEG under `receipts/` (or `RECEIPT_ROOT`) are supported, limited to 5 MB
and 20 megapixels. Absolute paths, traversal and symlink escape are blocked. PDFs
and remote URLs are not supported. Failed, unreadable or invalid extraction is an
error envelope; no fake tax, date, total or confidence is inserted. Confidence is
model-reported and not calibrated. Successful vision usage is included in review
metadata totals and remains visible separately in its tool result. Unknown token
counts remain null.

The Day 4 limits remain: 12 model rounds, 48 total tool calls, repeat-call detection,
and 150,000 serialized context characters. Day 5 may need a correction round.
Queue writes remain opt-in with `--queue`; completed validated proposals only.
Direct Inspector access to `save_decision` remains the historical schema-only mock
queue interface: the independent review verifier is enforced by the agent runner.
Nothing executes a payment or sends the drafted query.

Citation existence does not prove that every word of model-written prose is true.
The verifier checks the supported structured facts and teaching-policy conditions;
it is not a general proof engine, receipt-authenticity detector or production
approval system. Batch scoring, accuracy and latency benchmarks remain Day 6.

## Troubleshooting

- `VISION_DISABLED`: add the vision setting above and rerun the command.
- `VISION_API_ERROR`: inspect the safe error hint; check image support and model access.
- `RECEIPT_UNREADABLE` / `RECEIPT_EXTRACTION_INVALID`: use a clearer image or manual review.
- `API request timed out`: the trace now distinguishes timeout from other connection errors.
- `STEP_BUDGET_EXHAUSTED`: inspect `validation_feedback` in the last trace steps.
- `queued: false`: expected unless `--queue` was supplied; repeated different decisions
  for an existing report ID can conflict with the mock ledger's idempotency rule.

Your previous commands `app.day4` still work in this ZIP and use the same stronger
checks. Historical DAY1–DAY4 files describe their original milestones. Start with
this file for the current behavior.

## Updating the reconciliation fix

If Day 5 is already installed, extract this updated archive separately and copy
`app/assembler.py`, `app/policy_guard.py` and `agent/prompts.py` into the matching
folders of your existing installation. Keep your working `.env` and `.venv`.
No new dependencies or mock-server restart are required for this correction.
Rerun EVAL-24. L21 should be `missing_receipt`, linked to `TX-EVAL-24-20` with
a zero delta; the extra missing-transaction DATA-QUALITY finding should be gone.
