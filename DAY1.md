# TripLedger — Day 1 only

A runnable Python foundation for the travel-expense compliance project in your screenshots.
Python 3.11 or 3.12 is recommended for this delivery; verification used Python 3.12.

## What is complete

- Repository scaffold following section 13, `.env.example`, and `.gitignore`.
- Custom chat API client with token-usage logging and a live smoke-test command.
- Optional, separately configured custom embedding client and smoke-test command.
- Pydantic report and decision contracts, plus exported JSON schemas.
- Pure `compute_totals` with exact Decimal arithmetic, line-level details and unit tests.
- Ruff linter, mypy type checker and pytest commands.

This is the **Day 1 foundation**, not the finished compliance agent. It does not
review reports autonomously, fetch transactions, run an MCP server, extract receipts,
apply all ten policy rules, approve expenses, or send payments/messages.
Files for later days are explicitly marked as reserved. No database is needed.

The assignment's early summary says seven tools, but section 11 and Day 3 specify
nine. Follow the later nine-tool contract when implementing Day 3.

## Windows PowerShell setup

Extract the ZIP and open a terminal inside `tripledger-day1`:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

If you have Python 3.11 instead, use `py -3.11`. These commands do not require
activating the environment or changing PowerShell execution policy.
Dependencies use version ranges; `requirements-lock.txt` records the environment
tested for this delivery. Use `pip install -r requirements-lock.txt` to reproduce it.

Linux/macOS equivalent:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
cp .env.example .env
```

Use `.venv/bin/python` instead of `.\.venv\Scripts\python.exe` in the commands below.
Run all commands from the extracted project root.

## 1. Run the Day 1 acceptance checks — no API key needed

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_compute.py -q
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy
```

The first command is the assignment's explicit Day 1 done-when gate. The complete
suite also checks schema validation and model request/response handling offline.
Mock transport tests do not contact or prove access to your real API.

## 2. Understand the calculator

```powershell
.\.venv\Scripts\python.exe -m app.cli compute examples/compute-request.json
```

The illustrative hotel costs EUR 412 for 3 nights. The supplied cap is EUR 120
per night: the tool permits EUR 360 and disallows only EUR 52. With the example
taxi and meal, totals are **EUR 494.40 reimbursable** and **EUR 52.00 disallowed**.
This allowance is illustrative: the screenshots do not supply the per-city table.

```powershell
.\.venv\Scripts\python.exe -m app.cli compute examples/whole-line-request.json
```

Here `whole_line` disallows all EUR 75.50. Cap values are passed into the tool;
they are never embedded as policy constants in the calculator.

Input contract:

```json
{
  "base_currency": "EUR",
  "lines": [{"line_id": "L1", "amount": "412.00", "currency": "EUR"}],
  "caps": [{"line_id": "L1", "rule_id": "R-03", "kind": "cap_excess",
            "limit": "120.00", "quantity": 3}]
}
```

- `limit` means allowance **per unit**; `quantity` is nights/people/etc. supplied by
  the caller. Quantity defaults to 1. Extracting these facts is later work.
- `whole_line` takes no limit or quantity.
- Each original line and its effective cap are rounded to two decimals using
  `ROUND_HALF_UP` before aggregation. Decimal precision is 40 inside computation.
- Overlapping rules use the strictest allowed amount; disallowed amounts are not
  added twice. Per-rule excesses are explanatory and must not be summed together.
- Mixed currencies are rejected; Day 2 FX must convert them first.
- Negative/refund lines are deliberately rejected in this Day 1 contract.
- Two-decimal money is a documented simplification for the assignment's EUR demo;
  zero/three-minor-unit currencies need a later explicit currency precision policy.
- Outputs are decimal strings to preserve exact values in JSON. Inputs accept
  numbers or decimal strings; CLI JSON numbers are parsed directly as Decimal.

## 3. Validate the schemas

```powershell
.\.venv\Scripts\python.exe -m app.cli validate-report examples/report.json
.\.venv\Scripts\python.exe -m app.cli validate-decision examples/decision.json
.\.venv\Scripts\python.exe -m app.cli export-schemas
```

`mcp_server/schemas.py` is the source of truth. Exported contracts live in
`schemas/`. Unknown fields, negative money, invalid dates, duplicate report line
IDs, invalid decision enums, and findings without evidence are rejected.

Decision validation here checks structure, not the Day 5 policy gates or whether
evidence references really exist. The example decision is an illustrative fixture,
not an output generated by an agent. Receipt paths are illustrative and no image
files are supplied. `duplicate_candidates` has an explicitly chosen inner shape
because the screenshot shows only an empty array.

## 4. Configure YOUR custom LLM API

Edit `.env` locally. Never paste your key into source code or commit `.env`.

```dotenv
LLM_BASE_URL=https://your-company-host.example/v1
LLM_API_KEY=your-key
LLM_MODEL=your-model-name
```

The client appends `/chat/completions` to the base URL **exactly once**. Include
your provider's required version prefix yourself. If your URL is already the full
endpoint, or uses a custom route/query string, configure this instead:

```dotenv
LLM_ENDPOINT_URL=https://your-company-host.example/custom/chat/completions
```

`LLM_ENDPOINT_URL` overrides the base URL. The client does not guess `/v1` or
rewrite deployment URLs. Authentication defaults to `Authorization: Bearer KEY`.
For a provider requiring `api-key: KEY`, set:

```dotenv
LLM_AUTH_HEADER=api-key
LLM_AUTH_SCHEME=
```

If your model rejects temperature, leave `LLM_TEMPERATURE=` blank. Optional
provider body fields can be set with `LLM_EXTRA_BODY_JSON`, for example
`{"max_completion_tokens":64}`. Core fields cannot be overridden through it.

Run the real connection check:

```powershell
.\.venv\Scripts\python.exe -m app.cli llm-smoke
```

It sends only a fixed synthetic greeting, verifies a chat response, prints `ok`
and token counts, and appends a metadata-only event to `traces/usage.jsonl`.
If the provider omits token usage, counts are `null`; they are not fabricated.
A successful live response with usage completes the remaining connection gate.
The live call could not be performed during delivery because your URL/key/model
were not supplied.

**Compatibility assumption:** the chat API accepts an OpenAI-compatible
`model/messages` request and returns `choices[0].message`. A custom URL alone
does not imply that format. If your API differs, adapt
`integrations/model_client.py` using its documented request/response sample.
No OpenAI SDK or direct OpenAI service is required.

## 5. Optional custom embedding API

Embeddings are not required for Day 1 or exact arithmetic. This project does not
create a vector database or embed reports automatically. Chat works without any
embedding configuration.

```dotenv
EMBEDDING_BASE_URL=https://your-company-host.example/v1
EMBEDDING_API_KEY=your-embedding-key
EMBEDDING_MODEL=your-embedding-model
EMBEDDING_DIMENSIONS=
```

The default endpoint is `BASE_URL/embeddings`; `EMBEDDING_ENDPOINT_URL` overrides it.
Leave dimensions blank unless your provider explicitly supports that parameter.
For the standard format, the request uses `input: [text]` and the response vector
is read from `data[0].embedding`.

For a custom endpoint accepting a scalar `inputText` and returning `embedding`:

```dotenv
EMBEDDING_INPUT_FIELD=inputText
EMBEDDING_INPUT_AS_LIST=false
EMBEDDING_VECTOR_PATH=embedding
```

The request still includes `model`; if your endpoint disallows that or needs more
complex signing/format changes, adapt the provider file. Authentication header,
scheme and extra request fields have separate `EMBEDDING_...` settings.

```powershell
.\.venv\Scripts\python.exe -m app.cli embedding-smoke
```

This checks a real vector and prints its dimensions without printing the vector.
Embedding failure does not prevent running any Day 1 calculation or schema check.

## Troubleshooting

| Symptom | What to check |
|---|---|
| 400 | Request format, model, extra fields; try blank temperature/dimensions |
| 401 | Key and authentication header/scheme |
| 403 | Gateway/model permission; retries cannot fix an access denial |
| 404 | Full endpoint path, version prefix, deployment/model name |
| 429 / 5xx | Three retries with exponential backoff and jitter, then a clear error |
| Network / TLS error | Corporate VPN/proxy and `CA_BUNDLE`; TLS verification is enabled |
| Unexpected response shape | Adapt `integrations/model_client.py` to provider documentation |

Logs contain request IDs, timestamps, latency and numeric token usage only. Keys,
URLs, prompt contents and provider error bodies are not logged. Day 1 does not
implement the full intake redaction pipeline: use only synthetic fixtures, and
the supplied smoke commands send no report contents.

## How the files connect

1. `app/cli.py` reads a command and validates its input.
2. `mcp_server/schemas.py` defines the report, decision and calculation contracts.
3. `mcp_server/tools_compute.py` performs deterministic money calculations.
4. `app/config.py` loads separate custom endpoint settings from `.env`.
5. `integrations/model_client.py` performs chat or embedding API requests.
6. `tests/` demonstrates the acceptance behavior without internet access.

Day 2 adds mock systems and dated FX. Day 3 exposes tools/resources via MCP.
Day 4 introduces the actual agent. Those stages are intentionally left for later.

Implementation references: [Pydantic models](https://docs.pydantic.dev/latest/concepts/models/)
and [HTTPX mock transports](https://www.python-httpx.org/advanced/transports/#mock-transports).
