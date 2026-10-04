# Day 7 — Local review dashboard

Day 7 adds a browser interface on top of the corrected Day 6 review pipeline.
It does not change the model prompt, verifier, financial calculations, evidence
rules or the 12-step limit. The EVAL-21 exact-delta recovery fix is included.

## Start on Windows

Extract this archive into a new folder. Open PowerShell in `tripledger-day7`,
where `app` and `requirements-dev.txt` are located. Copy your working Day 6 `.env`
into this folder. Keep the custom URL, model, key, CA and timeout settings.
Do not copy your old virtual environment; create one for the new folder:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

Stop the previous mock process. Start this package's mocks in terminal 1:

```powershell
.\.venv\Scripts\python.exe -m mock_systems.run
```

In terminal 2, from the same project folder:

```powershell
.\.venv\Scripts\python.exe -m app.day7
```

Open the **complete URL printed in the terminal**, including `#token=...`.
The page runs at `http://127.0.0.1:8090`. The token is required for its API;
it is separate from your provider API key, which stays in the server environment.
The browser removes the fragment from the address bar after keeping the token in
session storage. After restarting the server, open its newly printed URL.

If another application uses port 8090:

```powershell
.\.venv\Scripts\python.exe -m app.day7 --port 8091
```

Only one dashboard may run against a project folder, even on different ports.
There are no new Python dependencies beyond Day 6. No npm or frontend build needed.

## First live check

1. Select **EVAL-01 · Clean expense**, then click **Load**.
2. Inspect the JSON, then click **Start review**. This makes real API calls.
3. Wait for the status to become **complete**. The page polls every 2.5 seconds;
   it shows overall job status, not individual model/tool steps.
4. Expect **auto_approve**, EUR 20 reimbursable, EUR 0 disallowed and no findings.
5. Download **Result JSON** or **Trace JSON**, or select the run from history.

The model still chooses its tools. The web server calls the same `review()` used
by the CLI, with `max_steps=12` and `queue=False`. It never sends draft queries,
submits to the mock queue or executes payments. `auto_approve` is a proposal.

Additional checks:

| Demo | Expected outcome |
|---|---|
| EVAL-24 · Missing receipt | manager_review; R-02 on L21; EUR 45 / EUR 0; L21 missing_receipt with TX-EVAL-24-20 |
| EVAL-21 · Injection case | manager_review; R-07; EUR 0 / EUR 20; matching delta 0 |
| VISION-01 · Image receipt | auto_approve; EUR 20 / EUR 0, if extraction succeeds consistently |

For the image example, retain `RECEIPT_VISION_ENABLED=true` in `.env`.
Blank `VISION_MODEL` uses the configured chat model. These examples were live-tested
in earlier stages; Day 7's browser-to-corporate-API flow must be checked locally.

## Input and saved reviews

Choose an existing report JSON file or paste JSON into the editor. The existing
Pydantic intake validates and redacts it before review. Requests larger than 1 MiB
are rejected. Receipt paths must refer to files already under the project's
receipt directory and pass the existing receipt scope checks. This release does
not upload images or arbitrary files from the browser.

One review runs at a time. A second API submission receives HTTP 409. Reloading
or closing the browser does not cancel a running server-side review. Keep both
PowerShell processes running until completion. History belongs to this Day 7
folder; Day 6 evaluation directories remain separate and are never rewritten.

Each job is saved under `runtime/dashboard/<job-id>/`:

- `job.json`: status, report ID, timestamps and completed/incomplete result.
- `result.json`: the accepted result or safe incomplete fallback.
- `trace.json`: redacted inputs, tool evidence, validation feedback and usage.

Files are replaced atomically. If the process stops while a job is running,
the next startup marks it **interrupted**. It does not automatically repeat
potentially billable work. Load the report and deliberately start a new review
if you want to retry. A crash can leave artifacts alongside an interrupted job;
that job is not advertised as completed.

For an incomplete run, open the result's reason and download the trace to inspect
provider errors and validation feedback. For a failed job, the browser shows only
the exception type. Check `.env`, mock processes and folder permissions. A
configuration failure may appear as `ConfigurationError`. Existing CLI commands
remain available for diagnosis:

```powershell
.\.venv\Scripts\python.exe -m app.day5 --report evals/reports/EVAL-01.json
.\.venv\Scripts\python.exe -m app.receipt_smoke receipts/day5/sample-taxi.png
```

## Local scope

This is a single-user localhost demo built with Python's standard-library HTTP
server. It binds only to 127.0.0.1 and validates the Host, Origin (when present)
and per-launch API token. It serves only explicitly allowed assets, examples
and job artifact names; there is no general file server. Dynamic report content
is inserted as text, not HTML. Browser responses disable caching and framing.

This is not a deployed multi-user service. It has no organizational login,
role-based access or encrypted artifact store. Existing intake redaction is
pattern-based and is not a guarantee of complete personal-data removal. Use
the synthetic demo reports. No provider credentials are supplied by the browser.

## Evaluation continuity

Your reported original Day 6 suite passed 24/25 (96%) on first attempts with
zero unsafe auto-approvals. EVAL-21 then passed in a separate recovery run after
the feedback fix. This is not a fresh 100% full-suite score on this package.
The dashboard does not generate evaluation scores. Use the existing runner in
a new directory if you want to measure the whole suite again:

```powershell
.\.venv\Scripts\python.exe -m app.day6 --run-dir runtime/evals/day7-full
```

Do not resume older runs after source changes: the evaluation fingerprint guards
against mixing configurations. Preserve the earlier results.
