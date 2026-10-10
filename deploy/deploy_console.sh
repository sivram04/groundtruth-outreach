#!/bin/sh
# Build the console (the React pages and the Python service that serves them their data) and
# deploy it behind Google's sign-in gate (IAP). Run from anywhere; setup_console.sh first.
#
# Private: IAP lets through only the accounts granted in setup_console.sh (admin@lakshyaa.ai),
# and the console itself checks IAP's signed token on every request against the audience and
# the allow-list below. It only reads, so it has no scheduler and no tag to test first.
#
# The drafting settings (outreach-settings) and the Google sign-in token come from Secret
# Manager. Update the settings after a local change with:
#   gcloud secrets versions add outreach-settings --data-file=.secrets/pilot_handbook.json \
#     --project=lakshyaa-outreach
set -e
cd "$(dirname "$0")/.."
P=lakshyaa-outreach
R=us-central1
NUMBER=$(gcloud projects describe $P --format='value(projectNumber)')
IMAGE=$R-docker.pkg.dev/$P/cloud-run-source-deploy/outreach-console:$(date -u +%Y%m%d-%H%M%S)
HANDBOOK=1lnKJMRZe0QPyxFZaV6zNq_GI-HNudncnW1uzrvwzeuU

gcloud builds submit --project=$P --config=deploy/console.cloudbuild.yaml \
  --substitutions=_IMAGE=$IMAGE .
# The settings go in a file: Git Bash on Windows would rewrite /projects/... on the command
# line into a Windows path, and switching that rewriting off breaks gcloud's own launcher.
ENV_FILE=.console-env.yaml
trap 'rm -f $ENV_FILE' EXIT
cat > $ENV_FILE <<YAML
CONSOLE_IAP_AUDIENCE: "/projects/$NUMBER/locations/$R/services/outreach-console"
CONSOLE_ALLOWED_EMAILS: "admin@lakshyaa.ai"
HANDBOOK_DOC_ID: "$HANDBOOK"
ENABLE_REVIEW: "true"
REVIEW_STORE: "sheet"
ENABLE_SEND: "true"
ENABLE_LEAD_CHAT: "true"
ENABLE_GMAIL_DRAFTS: "true"
ENABLE_PLAYBOOK: "true"
ENABLE_IMPORT: "true"
YAML
gcloud run deploy outreach-console --image=$IMAGE --region=$R --project=$P \
  --service-account=outreach-console@$P.iam.gserviceaccount.com \
  --no-allow-unauthenticated --iap \
  --max-instances=2 --concurrency=8 --timeout=60 --memory=512Mi \
    --set-secrets=GOOGLE_SIGNIN_TOKEN=google-signin-token:latest,OUTREACH_HANDBOOK_JSON=outreach-settings:latest,REVIEW_PRIVATE_KEY=review-signing-key:latest \
  --env-vars-file=$ENV_FILE \
  --quiet
# Traffic was once pinned to a tagged revision ("next"), so a plain deploy left new revisions at 0%.
# Always move 100% of traffic to the revision just deployed.
gcloud run services update-traffic outreach-console --region=$R --project=$P --to-latest --quiet
