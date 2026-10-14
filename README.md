# TripLedger Platform

A single-organization expense workspace: React frontend, four Java Spring Boot
applications (gateway, identity, expense, policy), and a Python AI service with a
separate background worker. Employees submit reports; assigned managers make
final decisions; administrators manage access and publish policy versions.

## Included

- Employee forms, saved drafts, private PNG/JPEG receipt uploads, and report history.
- Manager inbox, evidence and AI findings, clarification, approval and rejection.
- Admin accounts, roles, manager assignments, immutable policy versions and publication.
- Opaque bearer sessions, BCrypt passwords, server-side report authorization,
  password changes, session revocation, and per-gateway sign-in throttling.
- PostgreSQL per service, Flyway Java migrations, pgvector policy retrieval.
- Durable submission outbox, RabbitMQ publisher confirms, idempotent AI callbacks.
- Python tool calling, optional vision extraction, exact decimal cap calculations,
  date checks, receipt mismatches, duplicate receipt hashes, date-based FX caching.
- Custom chat/embedding endpoints, keys, model names, auth headers and CA bundles.
- Architecture, API, workflow and deployment guides in `docs/`.

The project is a working development baseline, not a claim of production certification.
It requires your database, RabbitMQ and model configuration. There are no embedded
provider keys, public demo accounts, fake successful reviews, or payment operations.

## Requirements

- JDK 17 or 21; Maven 3.9+ (`java -version`, `mvn -version`).
- Python 3.11 or 3.12 recommended.
- Node.js 20.19+ or 22.12+ and npm.
- PostgreSQL 17 with pgvector, plus RabbitMQ. Each may run locally or as optional
  infrastructure containers. Java, Python and React run on your computer.

`pgAdmin` manages PostgreSQL; it is not the database server. Configure the actual
PostgreSQL server port. A local PostgreSQL installation commonly uses 5432; this
project's optional container publishes 5433 to avoid that collision.

## Windows quick start

Run from the extracted `tripledger-platform` folder. Do not reuse the old project's
virtual environment or point these new services at its database tables.

### 1. Create configuration and install dependencies

```powershell
py -3.12 -m venv ai-service/.venv
.\ai-service\.venv\Scripts\python.exe -m pip install -r ai-service/requirements.txt
.\ai-service\.venv\Scripts\python.exe scripts/configure.py
npm ci --prefix frontend
mvn clean verify
npm run build --prefix frontend
```

Use `py -3.11` if Python 3.12 is not installed. `configure.py` creates `.env` with
random local secrets and refuses to overwrite an existing file. Open `.env` and
set your company chat and embedding endpoints, API keys and model names. The
administrator email/password are `BOOTSTRAP_ADMIN_EMAIL` and
`BOOTSTRAP_ADMIN_PASSWORD`; they are applied only to an empty identity database.

The Python PostgreSQL driver is **pg8000**, which does not require psycopg/libpq DLLs.
The Java services use the PostgreSQL JDBC driver.

### 2. Choose infrastructure

**Option A: optional Docker PostgreSQL + RabbitMQ**

```powershell
docker compose up -d --wait postgres rabbitmq
```

Keep the JDBC URLs and AI URL using `127.0.0.1:5433`. Application services are not
containerized. Existing named volume passwords do not change just because `.env`
changes; use the existing password or change it through PostgreSQL administration.
Do not delete volumes to fix an authentication issue.

**Option B: local PostgreSQL + RabbitMQ**

Install pgvector for your PostgreSQL server. Edit these `.env` entries:

```dotenv
DB_USER=your_postgres_user
DB_PASSWORD=your_postgres_password
IDENTITY_JDBC_URL=jdbc:postgresql://127.0.0.1:5432/tripledger_identity
EXPENSE_JDBC_URL=jdbc:postgresql://127.0.0.1:5432/tripledger_expense
POLICY_JDBC_URL=jdbc:postgresql://127.0.0.1:5432/tripledger_policy
AI_DATABASE_URL=postgresql://your_postgres_user:URL_ENCODED_PASSWORD@127.0.0.1:5432/tripledger_ai
```

URI-encode special characters only in the AI connection URL password. For example,
`@` becomes `%40`. `DB_PASSWORD` holds the original password. Set RabbitMQ credentials
to match your local broker. Alternatively run only the broker in Docker:

```powershell
docker compose up -d --wait rabbitmq
```

No Docker is required when both PostgreSQL and RabbitMQ are installed locally.
Never use `host.docker.internal` or `postgres` as the database hostname for these
locally running application processes.

### 3. Create databases and initialize AI storage

```powershell
.\ai-service\.venv\Scripts\python.exe scripts/create_databases.py
Push-Location ai-service
.\.venv\Scripts\python.exe -m app.database
Pop-Location
```

The database user needs permission to create databases and install the vector
extension. If it does not, have a DBA run `infra/create-databases.sql` and install
`vector` in `tripledger_ai`. The Java services apply their own migrations on startup.
The helper creates the four standard database names; if you use different names,
create them manually and update all corresponding URLs.

### 4. Start applications locally

```powershell
.\scripts\start-local.ps1
```

This opens seven terminal windows. Keep them open. If script execution is blocked
by your workstation policy, run the commands below in separate terminals instead;
there is no need to change the machine's execution policy.

```powershell
.\ai-service\.venv\Scripts\python.exe scripts/run.py identity
.\ai-service\.venv\Scripts\python.exe scripts/run.py expense
.\ai-service\.venv\Scripts\python.exe scripts/run.py policy
.\ai-service\.venv\Scripts\python.exe scripts/run.py gateway
.\ai-service\.venv\Scripts\python.exe scripts/run.py ai-api
.\ai-service\.venv\Scripts\python.exe scripts/run.py ai-worker
.\ai-service\.venv\Scripts\python.exe scripts/run.py frontend
```

The launcher loads the root `.env`; plain `java -jar` does not automatically load
it. In IntelliJ, supply the same environment variables to each service run configuration.
Start the Python API as well as the worker: the API indexes policies; the worker
consumes queued reports. Close terminals with Ctrl+C to stop services.

Open **http://127.0.0.1:5173**.

### 5. First usable workflow

1. Sign in using the bootstrap administrator credentials in `.env`.
2. In **People & access**, create a manager, then an employee assigned to that manager.
   Give each a different initial password of at least 12 characters. They can change
   their own password in **My account**.
3. In **Expense policies**, create a policy. Paste `examples/travel-policy.md` and
   enter its three matching structured limits. Click **Save policy draft**, then
   **Index & publish version**. This makes real embedding API calls.
4. Sign out. Sign in as the employee, create a report and save the draft.
5. Upload PNG/JPEG receipts to expense lines; save again or submit. Uploads are real
   private files stored in the Expense Service database, not browser file paths.
6. Submit. The report is frozen as a revision and queued for AI review. This makes
   real chat calls, embedding search calls, and optional vision calls. Cross-currency
   claims call the configured FX service.
7. Sign in as the assigned manager. Read the report, receipt downloads, AI findings,
   policy citations and calculations. Approve, reject, or request clarification.
8. For clarification, the employee edits the returned report and resubmits. The old
   snapshot/review remains available. Approval records an amount but does not pay it.

If AI fails, the manager can review manually or the manager/admin can retry. A
provider error is never converted into an automatic approval.

## Ports

| Component | Port |
|---|---:|
| React (development) | 5173 |
| API Gateway | 8080 |
| Identity Service | 8081 |
| Expense Service | 8082 |
| Policy Service | 8083 |
| Python indexing API | 8090 |
| Python worker | no HTTP port |
| Optional PostgreSQL container | 5433 |
| RabbitMQ / management | 5672 / 15672 |

If the original TripLedger dashboard is using 8090, stop it before starting this
project. Only the frontend/gateway should be exposed when deploying for other people.

## Provider settings

Use either `LLM_BASE_URL=https://provider.example/v1` or a full
`LLM_ENDPOINT_URL=https://provider.example/v1/chat/completions`. A nonempty endpoint
is the complete URL and takes precedence; do not set it to a relative path.
Configure embeddings the same way. Leave `LLM_TEMPERATURE` empty for models that do
not accept it. The chat API must support OpenAI-style tool calls. Embedding input
field, list/scalar input, vector response path, and optional dimensions are configurable.
Use `CA_BUNDLE` for a corporate PEM trust bundle; TLS verification remains enabled.
Provider settings never go to React. `RECEIPT_VISION_ENABLED=false` marks receipts
unverified; set it to true only with a compatible vision model/gateway.

## Checks

```powershell
mvn verify
npm run build --prefix frontend
Push-Location ai-service
.\.venv\Scripts\python.exe -m pytest -q
Pop-Location
```

A Postman collection is included at `examples/TripLedger.postman_collection.json`.
Set credentials as local collection variables; do not export or share real passwords.

See `docs/VALIDATION.md` for what was verified in the authoring environment and
what requires your infrastructure. Generated environments, test outputs, node_modules,
compiled JARs and credentials are excluded from this source archive.

## Scope and limits

- One organization, one primary role per account. Managers can also submit their own
  reports, but a different manager must be assigned to approve them.
- No corporate card, HR, travel-booking, payroll, email or payment integration is
  connected. External reconciliation is explicitly flagged for manual review.
- This is a replatformed workflow, not a claim that every legacy EVAL rule has been
  ported. Structured category/currency caps and receipt/date/hash checks are automated;
  other policy text is evidence for AI explanation and manager interpretation.
- Receipts are PNG/JPEG only, max 8 MB each, 100 uploads per report. Reports allow up
  to 50 lines. Policy input is text/Markdown, max 100 KB, with up to 100 structured rules.
- Receipt bytes are stored in PostgreSQL for a self-contained local deployment. An
  object-storage adapter is a future replacement when file volume grows.
- Current report list is the most recent 500 accessible reports. Direct report IDs
  and their audit/revision history remain retrievable.
- FX conversion requires a supported currency pair. An unavailable rate fails the AI
  review rather than inventing a conversion. Managers must verify any manual conversion.
- Policy vector search uses exact cosine search scoped to a version. It does not
  assume a fixed embedding dimension or configure a dimension-specific HNSW index.
- Broker processing is at-least-once, not exactly-once. Results/callbacks are idempotent;
  a crash during a provider request can incur another provider call on redelivery.

See `docs/DEPLOYMENT.md` before making this development workspace available to a team.
