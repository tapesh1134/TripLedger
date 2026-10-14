# Low-level design

## Repository map

```
api-gateway/       Allowlisted HTTP forwarding, local sign-in rate limit
identity-service/  Users, manager assignment, BCrypt and session introspection
expense-service/   Report lifecycle, private receipts, audit, outbox and callbacks
policy-service/    Versioned policy text/rules and indexing-before-publication
common/            Actor, security filter, errors, internal HTTP client, exact JSON
ai-service/app/    FastAPI indexing API, queue worker, provider, tools and checks
frontend/src/      React role views, forms, API client and responsive styles
scripts/           Secrets, database setup, environment-aware local launchers
infra/             Optional DBA SQL
examples/          Example policy text
```

## Storage

| Database/table | Key | Important fields |
|---|---|---|
| identity.people | id UUID | email unique, name, password_hash, role, manager_id, active |
| identity.sessions | token_hash | user_id, expires_at |
| identity.identity_audit | id | actor_id, action, subject_id, at |
| expense.reports | id UUID | employee_id/name, manager_id, payload JSONB, status, revision, row_version, policy_id, job_id, ai_status, ai_result, decision |
| expense.receipts | id UUID | report_id, safe display name, mime, SHA-256, private bytea |
| expense.revisions | report_id + revision | submitted payload, policy_id, submitted_at |
| expense.review_jobs | id UUID | report_id, revision, status, result, completed_at |
| expense.outbox | id UUID | event JSONB, sent_at, attempts, last_error |
| expense.audit | id | report_id, actor_id, action, note, at |
| policy.policies | id UUID | title, content, rules JSONB, status, created_by, error |
| policy.policy_audit | id | policy_id, actor_id, action, at |
| ai.policy_chunks | policy_id + chunk_id | content, model, vector |
| ai.reviews | job_id UUID | report_id, revision, result JSONB |
| ai.fx_cache | day + base + quote | rate NUMERIC |

## Report payload contract

`Draft` is a Java validated record. Fields:
- `title`, `purpose`, `destination`, `startDate`, `endDate`, `baseCurrency`, `rowVersion`.
- `lines`: 1–50 line items.
- Each line: `lineId`, `date`, `category`, `merchant`, `amount`, `currency`,
  `description`, optional `receiptId`, `hotelNights`, `attendeeCount`, `clientDinner`,
  `alcoholAmount`.

Amounts enter the browser as strings. Java deserializes to BigDecimal and serializes
BigDecimal as strings. Python uses Decimal; it never derives totals from JavaScript
floating-point sums or model prose. Currency identifiers are uppercase three-letter
codes; the FX provider determines which pairs are supported.

Report creation derives employee_id and employee_name from the authenticated Actor.
Submission derives manager_id from Identity and policy_id from Policy. Browser fields
cannot set these values. The draft's current fields are copied into a new revision.

## Concurrency and state mutations

Expense mutations use `SELECT ... FOR UPDATE` inside Spring transactions. The caller's
rowVersion must match the current row version. Saves, submissions, decisions, retries,
and reassignments increment that version. Receipt upload locks the draft and checks
ownership/status, but does not increment version because it does not change line items.
The caller must save its returned receiptId on the line. Unattached uploads remain private
and count toward the per-report limit; no automatic file deletion job is included.

Submission writes revision, job, outbox and status atomically. OutboxPublisher selects
pending rows with `FOR UPDATE SKIP LOCKED`; it marks sent only after the broker confirms.
On uncertainty it leaves the row pending, deliberately preferring duplicates over loss.

Completion locks the job. Completed/failed callbacks return success without overwriting.
The report update matches its current job_id and SUBMITTED state; late results remain in
history but cannot replace a newer revision's result.

Approved amounts are nonnegative and checked against the claimed total when determinable
from completed AI conversion or same-currency report lines. On failed mixed-currency
reviews, manual conversion and amount verification remain the manager's responsibility.
Every decision requires a reason and records currency, manager ID and time.

## Policy retrieval

`retrieval.index_policy` appends structured rules to policy text, chunks it at 1,500
characters with 200-character overlap, and embeds every chunk. It verifies consistent
dimensions before a single transaction replaces a version's index. A transaction advisory
lock prevents competing replacements for the same version. Each chunk records model name.

`retrieval.search` embeds the query and uses pgvector cosine distance, scoped to policy ID,
model and vector dimension. Five passages are returned. Missing/mismatched indexes fail
explicitly. Reindex retained policy versions after changing embedding models; old versions
are not silently searched using a different vector space.

## AI review implementation

1. Worker gets the immutable snapshot from `/internal/jobs/{id}`.
2. Receipt extraction obtains only receipts referenced by that snapshot. Images are
   validated with Pillow and bounded at 20 million pixels. Extraction confidence below
   0.85, disabled vision or extraction errors produce unverified evidence.
3. `checks.calculate` evaluates structured caps, trip date bounds, missing receipts,
   same-report receipt reuse, cross-report receipt hashes and receipt amount/date mismatches.
4. A rate is fetched per expense date when currencies differ. Cache key includes date,
   base and quote. Values are Decimal, positive and finite. Per-line converted amounts
   round half-up to two decimals; totals sum the rounded line values.
5. Initial policy retrieval and deterministic checks enter the model context. Tools can
   reread report/receipts/checks or retrieve additional passages. Tool trace stores names
   and steps rather than model private reasoning.
6. Final JSON contains only `summary` and `citations`, validated by Pydantic. Citation IDs
   must have been retrieved. Numeric review fields are attached from deterministic code.
7. Review result is committed to the AI database before delivery to Expense. If callback
   delivery fails, redelivery reuses the stored output instead of calling the model again.

Provider calls have bounded retries for transient errors, configurable timeout/auth,
custom CA trust and no secret-bearing response logging. Aggregate usage currently tracks
review chat steps; it does not include vision and embedding token costs. The UI labels
these as review usage, not a total invoice estimate.

## API handling

Common Security filter authenticates internal calls via constant-time service-key
comparison and browser requests via Identity introspection. Actuator health and login
are public; other controllers perform role and object-level checks. The gateway never
forwards X-Service-Key supplied by browsers and routes only allowlisted API prefixes.
It imposes a 10 MB request-body limit; receipt controller imposes the stricter 8 MB file
limit and magic-byte checks. Error responses omit stack traces, credentials and provider
bodies. RequestLog records request ID, method, path, status and elapsed time.

## Frontend behavior

React has role-specific navigation but relies on backend authorization. The API helper
adds Authorization and signs out on 401. The employee form saves monetary strings, supports
multiple rows and uploads private receipt bytes through multipart requests. Submission
first saves the form, then submits the latest rowVersion. Reports in SUBMITTED poll every
five seconds. Other views refresh explicitly, so unsaved drafts are not overwritten by a
background timer. Manager actions reload the latest detail after completion.

Reports expose separate current AI and final manager decisions. Previous submitted
snapshots and AI runs can be downloaded from report history. No raw JSON editing is
required for ordinary users or policy administrators.
