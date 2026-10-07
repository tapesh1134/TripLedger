CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS schema_versions (
    version integer PRIMARY KEY, installed_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS employees (
    employee_id text PRIMARY KEY, payload jsonb NOT NULL
);
CREATE TABLE IF NOT EXISTS trips (
    trip_id text PRIMARY KEY, employee_id text NOT NULL REFERENCES employees,
    payload jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS trips_employee_idx ON trips(employee_id);
CREATE TABLE IF NOT EXISTS card_transactions (
    txn_id text PRIMARY KEY, employee_id text NOT NULL REFERENCES employees,
    posted_date date NOT NULL, amount numeric(18,2) NOT NULL, currency text NOT NULL,
    payload jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS card_employee_date_idx
    ON card_transactions(employee_id, posted_date, txn_id);
CREATE TABLE IF NOT EXISTS settled_lines (
    id text PRIMARY KEY, employee_id text NOT NULL REFERENCES employees,
    expense_date date NOT NULL, settled_at date NOT NULL, payload jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS settled_employee_date_idx ON settled_lines(employee_id, expense_date);
CREATE TABLE IF NOT EXISTS app_settings (key text PRIMARY KEY, value jsonb NOT NULL);
CREATE TABLE IF NOT EXISTS review_jobs (
    id text PRIMARY KEY, report_id text NOT NULL, status text NOT NULL
        CHECK (status IN ('running','complete','incomplete','failed','interrupted')),
    created_at timestamptz NOT NULL, finished_at timestamptz,
    report jsonb NOT NULL, job jsonb NOT NULL, result jsonb, trace jsonb
);
CREATE INDEX IF NOT EXISTS review_jobs_created_idx ON review_jobs(created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS one_running_review ON review_jobs ((true)) WHERE status='running';
CREATE TABLE IF NOT EXISTS review_decisions (
    id text PRIMARY KEY, report_id text UNIQUE NOT NULL, payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
-- Unbounded vector permits provider-specific dimensions. Exact cosine search is
-- intentional for this small policy corpus; no approximate index can omit a rule.
CREATE TABLE IF NOT EXISTS policy_chunks (
    id text PRIMARY KEY, source_uri text NOT NULL, content text NOT NULL,
    corpus_hash text NOT NULL, embedding_profile text NOT NULL,
    dimensions integer NOT NULL CHECK (dimensions > 0), embedding vector NOT NULL,
    CHECK (vector_dims(embedding) = dimensions)
);
CREATE INDEX IF NOT EXISTS policy_profile_idx ON policy_chunks(embedding_profile, corpus_hash);
INSERT INTO schema_versions(version) VALUES (1) ON CONFLICT DO NOTHING;
