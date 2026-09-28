CREATE TABLE IF NOT EXISTS accounts (
    id uuid PRIMARY KEY,
    username text NOT NULL UNIQUE,
    password_hash text NOT NULL,
    active boolean NOT NULL DEFAULT true,
    failed_count integer NOT NULL DEFAULT 0,
    first_failed_at timestamptz,
    locked_until timestamptz
);

CREATE TABLE IF NOT EXISTS projects (
    id text PRIMARY KEY,
    name text NOT NULL
);

CREATE TABLE IF NOT EXISTS memberships (
    account_id uuid NOT NULL REFERENCES accounts(id),
    project_id text NOT NULL REFERENCES projects(id),
    role text NOT NULL CHECK (role IN ('Maker', 'DataApprover', 'SecurityApprover', 'Operator', 'Auditor')),
    PRIMARY KEY (account_id, project_id, role)
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash char(64) PRIMARY KEY,
    account_id uuid NOT NULL REFERENCES accounts(id),
    csrf_token text NOT NULL,
    created_at timestamptz NOT NULL,
    last_seen_at timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS sessions_account_idx ON sessions(account_id);

CREATE TABLE IF NOT EXISTS connections (
    id uuid PRIMARY KEY,
    project_id text NOT NULL REFERENCES projects(id),
    name text NOT NULL,
    kind text NOT NULL CHECK (kind IN ('mysql_source', 'doris_target')),
    host text NOT NULL,
    port integer NOT NULL CHECK (port BETWEEN 1 AND 65535),
    database_name text NOT NULL,
    state text NOT NULL DEFAULT 'draft_unready' CHECK (state = 'draft_unready'),
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS connections_project_id_idx ON connections(project_id, id);

CREATE TABLE IF NOT EXISTS pipelines (
    id uuid PRIMARY KEY,
    project_id text NOT NULL REFERENCES projects(id),
    source_connection_id uuid NOT NULL REFERENCES connections(id),
    target_connection_id uuid NOT NULL REFERENCES connections(id),
    order_table text NOT NULL,
    user_table text NOT NULL,
    cycle_description text NOT NULL,
    state text NOT NULL DEFAULT 'draft_unready' CHECK (state = 'draft_unready'),
    revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS pipelines_project_id_idx ON pipelines(project_id, id);

CREATE TABLE IF NOT EXISTS audit_events (
    id uuid PRIMARY KEY,
    project_id text NOT NULL REFERENCES projects(id),
    actor_id uuid NOT NULL REFERENCES accounts(id),
    action text NOT NULL,
    resource_id uuid NOT NULL,
    request_id uuid NOT NULL,
    created_at timestamptz NOT NULL
);
