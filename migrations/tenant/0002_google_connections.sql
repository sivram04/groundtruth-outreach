-- Apply once after 0001 with the migration owner. Runtime grants are separate.
CREATE TABLE tenant.google_auth_attempts (
    account_id uuid NOT NULL REFERENCES tenant.accounts(id) ON DELETE CASCADE,
    state_hash text NOT NULL,
    provider_subject text NOT NULL,
    kind text NOT NULL CHECK (kind IN ('gmail','drive')),
    nonce text NOT NULL,
    code_verifier text NOT NULL,
    expires_at timestamptz NOT NULL,
    PRIMARY KEY (account_id, state_hash)
);
CREATE INDEX google_auth_attempts_expiry_idx ON tenant.google_auth_attempts(expires_at);

CREATE TABLE tenant.google_connections (
    account_id uuid NOT NULL REFERENCES tenant.accounts(id) ON DELETE CASCADE,
    connection_id uuid NOT NULL,
    kind text NOT NULL CHECK (kind IN ('gmail','drive')),
    google_subject text NOT NULL,
    email text NOT NULL,
    scopes text[] NOT NULL,
    refresh_ciphertext bytea NOT NULL,
    kms_key_name text NOT NULL,
    connected_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, connection_id),
    UNIQUE (account_id, kind, google_subject)
);

ALTER TABLE tenant.google_auth_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant.google_auth_attempts FORCE ROW LEVEL SECURITY;
CREATE POLICY auth_attempts_by_tenant ON tenant.google_auth_attempts
    USING (account_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (account_id = nullif(current_setting('app.tenant_id', true), '')::uuid);

ALTER TABLE tenant.google_connections ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant.google_connections FORCE ROW LEVEL SECURITY;
CREATE POLICY google_connections_by_tenant ON tenant.google_connections
    USING (account_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (account_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
