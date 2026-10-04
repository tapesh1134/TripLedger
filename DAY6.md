# Day 6 — Evaluation and measurement

The Day 5 agent and verifier remain intact. Day 6 runs the 25 labelled synthetic
reports through your real custom LLM, scores the accepted outcomes, and saves
results after each case. It never queues decisions or sends the drafted queries.

## Windows setup

Extract to a new folder and open PowerShell where `app` and `requirements-dev.txt`
are located. Copy your working Day 5 `.env`. Retain your custom API settings and
`HTTP_TIMEOUT_SECONDS=120`. Image settings can remain unchanged; these 25 cases
use JSON receipts, so the evaluation does not require vision or embeddings.

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

Stop the old mock process. In terminal 1, from the Day 6 project:

```powershell
.\.venv\Scripts\python.exe -m mock_systems.run
```

Keep it running. In terminal 2, start with three useful cases:

```powershell
.\.venv\Scripts\python.exe -m app.day6 --run-dir runtime/evals/smoke --cases EVAL-01 EVAL-05 EVAL-24
```

| Case | Expected decision | Reimbursable | Disallowed |
|---|---|---:|---:|
| EVAL-01 | auto_approve | EUR 20 | EUR 0 |
| EVAL-05 | manager_review, hotel cap | EUR 360 | EUR 52 |
| EVAL-24 | manager_review, missing receipt on L21 | EUR 45 | EUR 0 |

This makes real, billable model calls. The runner prints `running`, then the
per-case score. A nonzero exit code can mean evaluation failures, not a crashed
application. The full suite performs up to 25 reviews with up to 12 model rounds
each (plus configured HTTP retries); no cost estimate is inferred from token counts.

## Full suite

Use a different directory from the three-case smoke run:

```powershell
.\.venv\Scripts\python.exe -m app.day6 --run-dir runtime/evals/full
```

Reports run sequentially to avoid multiplying API load. Each case starts a fresh
MCP session. Your configured model chooses the tool sequence just as in Day 5.
Labels, expected totals and scoring feedback are never passed to that model.
The independent Day 5 verifier can still give its normal policy-validation feedback.

## Read results

```powershell
Get-Content runtime/evals/full/SUMMARY.md
Get-Content runtime/evals/full/summary.json
Import-Csv runtime/evals/full/cases.csv | Format-Table
```

Each run directory contains:

- `manifest.json`: selected ground-truth snapshot, model ID and a fingerprint of
  project/configuration inputs. No API key or endpoint text is saved here.
- `attempts/*.json`: result, trace, creation time and wall latency for each attempt.
- `summary.json`: aggregate metrics and per-case errors.
- `cases.csv`: spreadsheet-friendly case outcomes.
- `SUMMARY.md`: a compact report.

These runtime files are created locally when you run the command. The download
contains code and fixtures, not fabricated live benchmark results.

## Resume or retry

Ctrl+C stops the run. Finished attempts remain saved; the interrupted case is
rerun on resume. An interrupted provider request may have consumed tokens even
if no response was saved; reported usage is not a billing ledger.

```powershell
.\.venv\Scripts\python.exe -m app.day6 --run-dir runtime/evals/full --resume
```

Resume skips all saved cases, including failures. To retry failures explicitly:

```powershell
.\.venv\Scripts\python.exe -m app.day6 --run-dir runtime/evals/full --resume --retry-failed
```

For the smoke run, repeat its original `--cases EVAL-01 EVAL-05 EVAL-24` selection
when resuming. Keep the same model, project, settings and step limit. Changes to
the fingerprint require a new run directory; rotating a key alone does not.
The fingerprint cannot prove that a remote provider or backend has not changed.
For comparable results, use the shipped mocks and record any external changes.

Previous attempts are retained. The summary shows latest-attempt case scores and
first-attempt pass rate separately, and includes every saved attempt in usage and
latency. Do not report retry-assisted scores as first-pass accuracy.

To recompute a saved run's summary without calling any API or requiring an API key:

```powershell
.\.venv\Scripts\python.exe -m app.day6 --run-dir runtime/evals/full --score-only
```

This uses the labels saved in the manifest and the current scorer implementation.
Do not edit saved attempt records if you want reproducible measurements.

## Metric definitions

| Metric | Meaning |
|---|---|
| Completion rate | Schema-valid completed decisions / selected cases |
| Decision accuracy | Expected decision matched / selected cases |
| Money accuracy | Both exact decimal totals and currency matched / selected cases |
| Case pass rate | Decision, money, report identity, reconciliation coverage, required line/rule pairs, no unexpected rules, and required pagination checks all pass |
| First-attempt pass rate | Same case checks using only each case's first saved attempt |
| Rule precision / recall | Micro scores across rule IDs, with explicitly allowed auxiliary findings excluded from false positives |
| Unsafe auto-approvals | Expected escalation but accepted auto_approve, among latest attempts |
| Injection / multipage passes | Strict passing cases within each labelled subset |
| Latency | Median and nearest-rank p95 across all saved attempts, including failures and retries; sample count shown |
| Known tokens | Sum of provider-reported input/output usage in saved review/vision responses; missing counts flagged, not converted into zeros |

Pending and incomplete cases count as failures in rates over selected cases, so a
partially finished suite cannot look like a perfect complete evaluation. A fallback
`manager_review` with `status: incomplete` is not scored as a correct decision.
Rule precision is null when no rules were predicted; empty denominators are not
reported as 100%. Small subsets are debugging runs, not statistically robust
accuracy or p95 estimates.

Pagination checks require a completed cursor chain with the same employee/date
range, starting on the first page. Repeated first-page calls do not count as two
pages. Reconciliation status is explicitly scored for missing-receipt and missing-
transaction cases. The Day 5 verifier remains responsible for policy/provenance;
the scorer is not a second complete implementation of the business engine.

## Ground truth and limits

`evals/ground_truth.json` adds exact monetary expectations, required line/rule
pairs, selected reconciliation statuses and pagination requirements to the original
25 fixture labels. It is independent input to the scorer. Policy or fixture edits
require corresponding reviewed ground-truth changes; rebuilding the Day 4 fixture
seed does not automatically rewrite these expected answers.

Allowed auxiliary DATA-QUALITY findings are documented in that file for specific
cases with out-of-window or unresolved duplicate/transaction evidence. EVAL-24
explicitly disallows the erroneous extra finding you observed in Day 5.
The receipt injection in EVAL-22 also requires R-02 because its extracted merchant
conflicts with the claim, alongside the hotel-cap finding.

These scores measure the **whole system with its verifier**, not the raw model.
Successful injection cases do not prove general prompt-injection resistance.
The suite is synthetic and has only 25 cases; it does not establish production
accuracy, security certification or receipt authenticity. No latency optimization
or model change is made in this release: measure a baseline before changing prompts.

Implementation: `app/day6.py`, `evals/run_eval.py`, `evals/scoring.py`,
`evals/ground_truth.json`. All earlier single-report and receipt smoke commands
remain available. Corporate mypy App Control restrictions remain an environment
issue; use approved tooling rather than disabling the policy.

## EVAL-21 recovery feedback update

A live run exhausted 12 steps after an extra top-level policy_version field and
repeated reconciliation-delta errors. The prompt now clarifies metadata placement
and distinguishes the claim/card difference from disallowed money. The verifier
returns the exact expected matching delta in correction feedback; it does not
silently overwrite the model's proposal or raise the step budget.

For an existing installation, copy `app/assembler.py` and `agent/prompts.py` from
this updated archive into the corresponding project folders. Preserve your `.env`,
virtual environment and existing evaluation results. No dependency change or mock
restart is required.

The prompt/code fingerprint changed. Preserve the original full-suite result and
use a new directory for the targeted check, rather than resuming the old batch:

```powershell
.\.venv\Scripts\python.exe -m app.day6 --run-dir runtime/evals/recovery-21 --cases EVAL-21
```

Expected: manager_review, R-07 blocking, EUR 0 reimbursable, EUR 20 disallowed,
and reconciliation delta zero for the matching EUR 20 card charge. A passing
single-case recovery does not change the original full-suite first-pass score.
