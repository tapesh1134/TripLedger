# Validation record

## Verified in the authoring environment

- Maven reactor build and test: common module and all four Spring Boot applications
  compiled and packaged successfully on Java 17. Seven focused workflow tests passed.
- React/Vite production build completed successfully.
- Four deterministic Python tests passed: hotel cap/excess, missing multiplier,
  decimal FX rounding, and receipt discrepancy without changing claimed money.
- Real Java HTTP services were exercised together against isolated PostgreSQL-compatible
  PGlite databases. The supplied SQL migrations were applied directly in this harness.
- Account creation, login, role restrictions and disabled-session rejection passed.
- Unauthorized report and receipt access returned 403; stale edits returned 409;
  submitted reports could not be edited.
- Multipart receipt upload and authenticated binary download preserved bytes.
- Exact decimal input `360.123456` survived Java storage and JSON responses unchanged.
- Policy publication invoked the real Python indexing endpoint and stored/retrieved
  pgvector data, using a fixture embedding API.
- The real Python worker processing function used tool calling with a fixture chat API,
  calculated EUR 300.00 reimbursable and EUR 60.12 disallowed, persisted its result,
  and delivered an idempotent callback to Java.
- Clarification, employee resubmission, a second immutable revision, manager approval,
  and preservation of revision history passed. Approval above the known claimed total
  was rejected.
- Headless Chromium checks passed for login, role navigation, form entry, adding/removing
  expenses, draft save and submission. Desktop and 390px-wide mobile screenshots were
  inspected. No JavaScript exceptions or page-level mobile horizontal overflow occurred.

## Not verified against your environment

- Your Windows workstation, corporate TLS setup, and actual chat/embedding/vision APIs.
- Live RabbitMQ delivery/confirmation/reconnect behavior: the integration harness invoked
  the worker processing function directly. The outbox/consumer implementation is included,
  but full broker testing requires the local setup in README.
- Flyway startup on PostgreSQL 17: the authoring harness applied migrations directly
  because its embedded database does not model Flyway advisory-lock behavior reliably.
- Real vision extraction, external FX API calls, production deployment/load, and all
  legacy case-study policy scenarios. Fixture providers do not establish real model accuracy.

The application does not silently enable fixture providers. You must configure real
provider endpoints for policy publication and AI review. Unit tests do not call paid APIs.

## Reproduce basic checks

From the repository root:

```text
mvn verify
npm ci --prefix frontend
npm run build --prefix frontend
```

From ai-service, using its virtual environment:

```text
python -m pytest -q
```

For infrastructure acceptance, follow the README first workflow with a dedicated test
employee, manager and small policy. Stop/restart the worker once while a report is queued,
then verify one final review result and audit history. Test a broker restart without
removing its volume. Do not run destructive recovery exercises on business data.
