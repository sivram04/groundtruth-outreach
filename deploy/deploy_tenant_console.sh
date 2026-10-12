#!/bin/sh
# Build the multi-tenant console (tenant-console/'s React pages and the Python service that
# serves them their data) and deploy it. Run from anywhere; deploy/setup_tenant_console.sh first.
#
# Behind IAP, like the single-tenant console - NOT because this needs IAP's one-org-identity
# model (it doesn't; this app's own Google sign-in is what actually resolves an account), but
# because the org's own "Domain Restricted Sharing" policy refuses to let any Cloud Run service
# in this project go truly public (--allow-unauthenticated's IAM binding fails outright - tried
# first, 2026-10-12). IAP is the same gate the founder already uses elsewhere, needs no org
# policy change, and setup_tenant_console.sh's `after-deploy` step grants exactly the people
# already on the OAuth consent screen's test-user list - nobody else can even reach the sign-in
# page. This does mean signing in twice (IAP's own Google check, then this app's own GSI
# sign-in) - redundant, but adds defense in depth rather than removing any.
#
# The OAuth client id/secret, the tenant database's password, and the persisted Flask secret all
# come from Secret Manager (deploy/setup_tenant_console.sh creates/grants them). Update the OAuth
# client after a real rotation with:
#   printf '%s' "$NEW_SECRET" | gcloud secrets versions add tenant-oauth-client-secret \
#     --data-file=- --project=lakshyaa-outreach
set -e
cd "$(dirname "$0")/.."
P=lakshyaa-outreach
R=us-central1
SQL_CONNECTION=$P:$R:outreach-tenant
KMS_KEY=projects/$P/locations/$R/keyRings/outreach-tenant/cryptoKeys/google-refresh
REDIRECT_URI=https://outreach-tenant-console-30387157876.$R.run.app/api/tenant/google/callback
IMAGE=$R-docker.pkg.dev/$P/cloud-run-source-deploy/outreach-tenant-console:$(date -u +%Y%m%d-%H%M%S)

gcloud builds submit --project=$P --config=deploy/tenant_console.cloudbuild.yaml \
  --substitutions=_IMAGE=$IMAGE .
# Env vars go in a file: Git Bash on Windows would rewrite /projects/... and /cloudsql/... on the
# command line into Windows paths (the same reason deploy_console.sh writes its settings to a
# file instead of passing them inline).
ENV_FILE=.tenant-console-env.yaml
trap 'rm -f $ENV_FILE' EXIT
cat > $ENV_FILE <<YAML
GOOGLE_OAUTH_REDIRECT_URI: "$REDIRECT_URI"
TENANT_TOKEN_KMS_KEY: "$KMS_KEY"
TENANT_DB_SOCKET: "/cloudsql/$SQL_CONNECTION"
TENANT_DB_USER: "postgres"
TENANT_DB_NAME: "postgres"
YAML
gcloud run deploy outreach-tenant-console --image=$IMAGE --region=$R --project=$P \
  --service-account=outreach-tenant-console@$P.iam.gserviceaccount.com \
  --no-allow-unauthenticated --iap --add-cloudsql-instances=$SQL_CONNECTION \
  --max-instances=2 --concurrency=8 --timeout=60 --memory=512Mi \
  --set-secrets=GOOGLE_OAUTH_CLIENT_ID=tenant-oauth-client-id:latest,GOOGLE_OAUTH_CLIENT_SECRET=tenant-oauth-client-secret:latest,TENANT_DB_PASSWORD=outreach-tenant-root-password:latest,TENANT_CONSOLE_SECRET_KEY=tenant-console-flask-secret:latest \
  --env-vars-file=$ENV_FILE \
  --quiet
# Always move 100% of traffic to the revision just deployed (see deploy_console.sh for why).
gcloud run services update-traffic outreach-tenant-console --region=$R --project=$P --to-latest --quiet
echo
echo "First deploy only: run 'sh deploy/setup_tenant_console.sh after-deploy' once to let IAP"
echo "call the service and let the founder + test users through its gate."
