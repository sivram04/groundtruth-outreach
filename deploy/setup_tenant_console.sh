#!/bin/sh
# One-time setup for the multi-tenant console. Run from the repository root, before the first
# deploy/deploy_tenant_console.sh.
#
# Behind IAP, like the single-tenant console - not because this app needs IAP's one-org-identity
# model (its own Google Identity Services sign-in is the real authentication; IAP is only an
# outer gate on who can even reach the sign-in page), but because the org's "Domain Restricted
# Sharing" policy refuses --allow-unauthenticated outright (confirmed 2026-10-12: the IAM binding
# for allUsers fails even when the flag is passed). Run this script once before the first deploy,
# then once more as `sh deploy/setup_tenant_console.sh after-deploy` right after it, to let IAP
# call the now-existing service and let the founder + test users through its gate - the same
# two-step order deploy_console.sh/setup_console.sh already use.
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
NUMBER=$(gcloud projects describe $P --format='value(projectNumber)')

if [ "$1" = "after-deploy" ]; then
  gcloud run services add-iam-policy-binding outreach-tenant-console --region=$R --project=$P \
    --member=serviceAccount:service-$NUMBER@gcp-sa-iap.iam.gserviceaccount.com \
    --role=roles/run.invoker
  # The same 3 people already on the OAuth consent screen's test-user list - nobody else can
  # even reach the sign-in page, let alone complete Google sign-in once there.
  for EMAIL in admin@lakshyaa.ai sivmm29@gmail.com marketing@finaccrual.com; do
    gcloud iap web add-iam-policy-binding --project=$P --region=$R \
      --resource-type=cloud-run --service=outreach-tenant-console \
      --member=user:$EMAIL --role=roles/iap.httpsResourceAccessor
  done
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
