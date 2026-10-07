# TripLedger

The entire Python application runs locally on your computer. You choose where
PostgreSQL with its pgvector extension runs by setting `DATABASE_URL`:

| Application | Database | Connection |
|---|---|---|
| Local Python | Locally installed PostgreSQL + pgvector | `127.0.0.1:5432` |
| Local Python | Optional Docker PostgreSQL + pgvector | `127.0.0.1:5433` |

There is no Python application container or Dockerfile. Compose is only an optional
database launcher. SQL records and pgvector embeddings use the same connection.
pgAdmin is a client for managing either database, not the database server itself.

## 1. Prepare local Python

Use Python 3.11+ and open PowerShell in the extracted project folder:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Copy `.env.example` only for a new installation; do not overwrite an existing
configured `.env`. Fill in your working custom chat and embedding URLs, keys and
models. Leave exact endpoint fields blank when using a compatible base URL, or
provide a full endpoint URL. Never commit credentials.

### Windows Application Control / Psycopg

The previously reported Windows policy block is independent of the database's
location. A Docker database does not change the driver's execution on Windows.
The local Python process needs a driver and client library allowed by your policy.

First check:

```powershell
.\.venv\Scripts\python.exe -c "import psycopg; print(psycopg.pq.__impl__)"
```

If the bundled binary DLL is blocked, an approved local PostgreSQL client library
can be used through Psycopg's supported Python implementation. Locate it:

```powershell
Get-ChildItem "C:\Program Files\PostgreSQL" -Filter libpq.dll -Recurse -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty FullName
```

If that installation is approved, use its real `bin` folder (17 is an example):

```powershell
$env:PATH = "C:\Program Files\PostgreSQL\17\bin;$env:PATH"
$env:PSYCOPG_IMPL = "python"
.\.venv\Scripts\python.exe -c "import psycopg; print(psycopg.pq.__impl__)"
```

Keep this PowerShell window for subsequent commands. These variables must be set
before Python starts; do not rely on `.env` for PSYCOPG_IMPL because driver imports
can precede dotenv loading. If the client library is missing or blocked, obtain an
approved client installation or an IT-approved driver. Do not disable Application
Control. The client library is needed even when the server runs in Docker.

## 2. Select a database

### Option A: local PostgreSQL + pgvector

No Docker commands are needed. In pgAdmin connect to your local PostgreSQL server
on port 5432 and create database `tripledger`. In that database's Query Tool:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
SELECT extversion FROM pg_extension WHERE extname = 'vector';
```

If `vector` is unavailable, install the approved pgvector server extension for your
local PostgreSQL version. Neither pgAdmin nor a Python package installs it.

Set in `.env`:

```dotenv
DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@127.0.0.1:5432/tripledger
POLICY_SEARCH_ENABLED=true
```

Use the real username, password and database name.

### Option B: Docker PostgreSQL + pgvector

Only the database runs in Docker; Python remains local. Configure `.env`:

```dotenv
DOCKER_POSTGRES_PORT=5433
DOCKER_POSTGRES_DB=tripledger
DOCKER_POSTGRES_USER=tripledger
DOCKER_POSTGRES_PASSWORD=YOUR_PASSWORD
DATABASE_URL=postgresql://tripledger:YOUR_PASSWORD@127.0.0.1:5433/tripledger
POLICY_SEARCH_ENABLED=true
```

Start Docker Desktop with Linux containers, then:

```powershell
docker compose up -d --wait postgres
```

The database is created on the volume's first initialization. Changing environment
values later does not change an existing database's password. Keep the actual
credentials for an existing volume. pgAdmin can connect to `127.0.0.1:5433`.

Both options use localhost because Python runs on your machine. Do not use
`host.docker.internal` or the service name `postgres` in these URLs. Percent-encode
special characters in URI passwords: `@` becomes `%40`, `#` becomes `%23`, `%`
becomes `%25`. The Docker password setting holds the original, unencoded password;
quote it in `.env` if needed to preserve literal dollar signs.

## 3. Initialize the selected database and start

Run these commands on Windows for either database option, after the driver import
check succeeds:

```powershell
.\.venv\Scripts\python.exe -m app.database init
.\.venv\Scripts\python.exe -m app.database seed
.\.venv\Scripts\python.exe -m app.database index-policies
.\.venv\Scripts\python.exe -m app.database status
.\.venv\Scripts\python.exe -m app.dashboard
```

`init` creates the extension/tables in the existing database. It requires suitable
permissions. `seed` inserts missing synthetic records without overwriting existing
ones. Indexing calls your embedding provider, and atomically replaces the policy
index after all embeddings succeed. Stop at any command that reports an error.

Open the complete printed URL, including its token:
`http://127.0.0.1:8090/#token=...`. Use `127.0.0.1` to satisfy Host-header validation.
Use **Try an example or import JSON → Clean expense → Load** to fill the form.
Expected synthetic result: complete, auto_approve,
EUR 20.00 reimbursable, EUR 0.00 disallowed.

### Fill out a report

Enter report ID, employee ID, trip ID and reimbursement currency. Add expenses
with date, merchant, category, amount and currency; include a business purpose.
Use existing employee and trip IDs from your selected database. Optional hotel
and meal details are available within each expense. Receipt paths point to files
already under `receipts/`; the form does not upload receipts.

Choose **Start review** to generate and submit the request automatically. No JSON
editing is required. **Generated JSON** offers a live preview and report download;
existing report JSON files can also be imported. Submission time is refreshed
when you start a review. Review results and trace downloads work as before.
Amounts are sent as decimal strings to preserve precision.

The main application and its MCP subprocess inherit the local process environment.
No `docker compose exec app` commands are used; there is no `app` service.

## Switching database targets

1. Stop the local dashboard with Ctrl+C.
2. Change `DATABASE_URL` in `.env`. Ensure there is no conflicting DATABASE_URL
   already exported in your PowerShell session: process environment takes precedence.
3. Ensure the selected server is running, then run init/seed for a new database.
4. Index policies for that database, then start `python -m app.dashboard` again.

A URL change switches storage; it does not migrate reports, history or embeddings.
Keep each database's records separately. Re-index after policy file changes or
embedding model/configuration changes. Missing/stale retrieval indexes produce an
incomplete review; `POLICY_SEARCH_ENABLED=false` explicitly enables SQL-only review.
All authoritative policy rules and deterministic validation still apply.

For Option B, `docker compose stop postgres` stops only the optional database.
Do not run `down -v` to fix an error: it deletes its database volume.

## Upgrading from the previous app-container package

Stop the previous setup from its old project folder using `docker compose stop`
to free dashboard port 8090. This keeps its named volumes. Extract this revision
into a new folder and create `.env` from this revision's example. Transfer only
working provider credentials and the database connection you choose. Remove old
PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD settings and container-only paths. Existing
Docker volumes are not automatically migrated or deleted. Keep the earlier folder
if you need to access its data. Avoid running two databases on the same host port.

## Project structure

| Path | Purpose |
|---|---|
| `app/dashboard.py` | Local dashboard entry point |
| `app/review.py` | CLI expense review |
| `app/evaluate.py` | Optional evaluation runner |
| `app/database.py` | Schema, seed, index and status |
| `app/mcp_check.py` | MCP diagnostics |
| `app/integration_cli.py` | Legacy HTTP diagnostics |
| `agent/` | Model orchestration, prompts and bounded history |
| `mcp_server/` | Tools, contracts, policies and deterministic calculations |
| `integrations/` | Custom model APIs, receipts and MCP client |
| `storage/` | SQL schema, repositories, jobs and vector search |
| `mock_systems/` | Synthetic seed records and optional legacy HTTP services |
| `evals/`, `tests/` | Optional evaluation data and regression checks |
| `receipts/samples/` | Sample receipt images |

There are no day-based filenames. Tests/evaluations do not execute on startup.

## Data flow

Validate/redact report → create SQL job → load full policies and retrieve vector
excerpts → LLM requests MCP tools → SQL supplies business evidence → tools match
transactions and calculate exact amounts → guards validate the proposal → save
result and trace atomically → display dashboard result.

SQL tables: employees, trips, card_transactions, settled_lines, review_jobs,
review_decisions, policy_chunks, app_settings, schema_versions. Dashboard results
and traces are stored in SQL. CLI/evaluation artifacts are saved under runtime.
The historical FX cache still uses a local SQLite file. Policy files remain the
authoritative source; vector search does not replace rule validation. The app does
not execute payments or provide a complete human override workflow. PDF receipt
support remains unimplemented.

## Optional developer commands

```powershell
.\.venv\Scripts\python.exe -m app.review --report evals/reports/EVAL-01.json
.\.venv\Scripts\python.exe -m app.evaluate --run-dir runtime/evals/new-run
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy
```

Native database tests use `TEST_DATABASE_URL` pointed at a disposable database with
pgvector. They create and remove their own temporary schemas. Ordinary tests isolate
database configuration and do not call your live model API.

## Validation scope

The underlying implementation passed 190 local tests and six PostgreSQL-compatible
integration checks with pgvector. This local-launch revision is checked with the
12 dashboard tests and static analysis. The authoring environment cannot verify
your Windows Application Control configuration, local database or Docker service;
the driver import check and one clean live review are needed on your computer.
