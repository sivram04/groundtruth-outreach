#!/bin/sh
# Deploy the private outreach worker. Setup done once on 2026-09-22:
#   - project lakshyaa-outreach, billing linked, APIs enabled
#   - service account outreach-worker@ with secretAccessor on google-signin-token
#   - default compute account granted roles/cloudbuild.builds.builder (builds from source)
set -e
cd "$(dirname "$0")/.."
gcloud run deploy outreach-worker --source=. --region=us-central1 --project=lakshyaa-outreach \
  --service-account=outreach-worker@lakshyaa-outreach.iam.gserviceaccount.com \
  --no-allow-unauthenticated --max-instances=1 --concurrency=1 --timeout=600 \
  --set-secrets=GOOGLE_SIGNIN_TOKEN=google-signin-token:latest --quiet
