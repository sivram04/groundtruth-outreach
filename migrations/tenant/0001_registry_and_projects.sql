-- First customer-tenant schema. Apply only with a dedicated migration role.
-- Runtime roles receive explicit grants in infrastructure, not ownership.
CREATE SCHEMA IF NOT EXISTS tenant;

CREATE TABLE tenant.accounts (
    id uuid PRIMARY KEY,
    name text NOT NULL CHECK (length(name) BETWEEN 1 AND 120),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE tenant.identities (
    provider_subject text PRIMARY KEY,
    account_id uuid NOT NULL REFERENCES tenant.accounts(id) ON DELETE CASCADE,
    email text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX identities_account_id_idx ON tenant.identities(account_id);

CREATE TABLE tenant.projects (
    account_id uuid NOT NULL REFERENCES tenant.accounts(id) ON DELETE CASCADE,
    project_id text NOT NULL CHECK (project_id ~ '^[a-z][a-z0-9-]{2,63}$'),
    name text NOT NULL CHECK (length(name) BETWEEN 1 AND 120),
    purpose text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, project_id)
);

ALTER TABLE tenant.projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant.projects FORCE ROW LEVEL SECURITY;
CREATE POLICY projects_by_tenant ON tenant.projects
    USING (account_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (account_id = nullif(current_setting('app.tenant_id', true), '')::uuid);

-- Provision non-owner, non-BYPASSRLS roles before use. The registry role gets
-- accounts/identities only; the data role gets projects only. A pool transaction
-- sets app.tenant_id with SET LOCAL and clears it at transaction end.
