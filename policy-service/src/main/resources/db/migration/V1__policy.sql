CREATE TABLE policies(id uuid PRIMARY KEY,title text NOT NULL,content text NOT NULL,rules jsonb NOT NULL,status text NOT NULL DEFAULT 'DRAFT',created_by uuid NOT NULL,created_at timestamptz NOT NULL DEFAULT now(),error text);
CREATE UNIQUE INDEX one_active_policy ON policies(status) WHERE status='ACTIVE';
CREATE TABLE policy_audit(id bigserial PRIMARY KEY,policy_id uuid NOT NULL,actor_id uuid NOT NULL,action text NOT NULL,at timestamptz NOT NULL DEFAULT now());
