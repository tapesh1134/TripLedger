CREATE TABLE people(id uuid PRIMARY KEY,email text UNIQUE NOT NULL,name text NOT NULL,password_hash text NOT NULL,role text NOT NULL CHECK(role IN ('ADMIN','MANAGER','EMPLOYEE')),manager_id uuid REFERENCES people(id),active boolean NOT NULL DEFAULT true,created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE sessions(token_hash text PRIMARY KEY,user_id uuid NOT NULL REFERENCES people(id),expires_at timestamptz NOT NULL);
CREATE TABLE identity_audit(id bigserial PRIMARY KEY,actor_id uuid,action text NOT NULL,subject_id uuid,at timestamptz NOT NULL DEFAULT now());
