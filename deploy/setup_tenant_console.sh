#!/bin/sh
# One-time setup for the multi-tenant console. Run from the repository root, before the first
# deploy/deploy_tenant_console.sh.
#
# Public (allUsers), not behind IAP - see deploy_tenant_console.sh for the full story of why IAP
# was tried first and dropped (2026-10-12): the org's "Domain Restricted Sharing" policy blocked
# IAP access for external accounts even after a project-scoped policy override, so the founder
# chose public access instead - this app's own Google sign-in plus Postgres RLS is the real
# security boundary either way. The allUsers invoker binding and the policy override are both
# one-time, already applied to the live service; this script no longer needs an `after-deploy`
# IAP-grant step.
#
# Creates:
#   1. The service's own service account - may read the OAuth client secret, the tenant
#      database's password, and the persisted Flask session-signing secret; may encrypt/decrypt
#      with the tenant KMS key; may connect to the tenant Cloud SQL instance via the Auth Proxy.
#   2. A persisted Flask secret (tenant-console-flask-secret) - generated here if it doesn't
#      exist yet, so a Cloud Run restart never logs everyone out (a random per-process secret,
#      the fallback outreach/tenant_console.py uses with none configured, would).
#
# Known simplification, recorded in docs/TENANCY_FOUNDATION.md: this service connects to
# Postgres as the SAME root user the founder used to prove the database live, not a narrower
# dedicated application role - the "two runtime roles (registry vs RLS-scoped data)" split that
# doc calls out as still open. Fine for the founder + one friend; revisit before this serves
# more people.
set -e
P=lakshyaa-outreach
R=us-central1
SA=outreach-tenant-console@$P.iam.gserviceaccount.com
KMS_KEY=projects/$P/locations/$R/keyRings/outreach-tenant/cryptoKeys/google-refresh

if [ "$1" = "after-deploy" ]; then
  # A project-scoped override of the org's "Domain Restricted Sharing" policy - without it,
  # --allow-unauthenticated's own IAM binding is refused outright (confirmed 2026-10-12). Affects
  # only this one project; every other project in the org keeps the strict default untouched.
  gcloud services enable orgpolicy.googleapis.com --project=$P
  cat > /tmp/allow-external-members.yaml <<YAML
name: projects/$P/policies/iam.allowedPolicyMemberDomains
spec:
  rules:
  - allowAll: true
YAML
  gcloud org-policies set-policy /tmp/allow-external-members.yaml --project=$P
  rm -f /tmp/allow-external-members.yaml
  gcloud run services add-iam-policy-binding outreach-tenant-console --region=$R --project=$P \
    --member=allUsers --role=roles/run.invoker
  exit 0
fi

gcloud iam service-accounts describe $SA --project=$P >/dev/null 2>&1 ||
  gcloud iam service-accounts create outreach-tenant-console --project=$P \
    --display-name="Multi-tenant outreach console: per-account Sheets/Gmail, its own Postgres"

for SECRET in tenant-oauth-client-id tenant-oauth-client-secret outreach-tenant-root-password; do
  gcloud secrets add-iam-policy-binding $SECRET --project=$P \
    --member=serviceAccount:$SA --role=roles/secretmanager.secretAccessor
done

gcloud secrets describe tenant-console-flask-secret --project=$P >/dev/null 2>&1 || {
  openssl rand -base64 32 | gcloud secrets create tenant-console-flask-secret --project=$P \
    --replication-policy=automatic --data-file=-
}
gcloud secrets add-iam-policy-binding tenant-console-flask-secret --project=$P \
  --member=serviceAccount:$SA --role=roles/secretmanager.secretAccessor

gcloud kms keys add-iam-policy-binding google-refresh --project=$P \
  --location=$R --keyring=outreach-tenant \
  --member=serviceAccount:$SA --role=roles/cloudkms.cryptoKeyEncrypterDecrypter

# Lets Cloud Run's Cloud SQL Auth Proxy sidecar (--add-cloudsql-instances) connect as this
# service account, over the Unix socket - no public-IP allowlisting needed.
gcloud projects add-iam-policy-binding $P --condition=None \
  --member=serviceAccount:$SA --role=roles/cloudsql.client

echo "Setup complete. KMS key for TENANT_TOKEN_KMS_KEY: $KMS_KEY"
