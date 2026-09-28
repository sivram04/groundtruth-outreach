#!/bin/sh
# Deploy the private outreach worker. Setup done once on 2026-09-22:
#   - project lakshyaa-outreach, billing linked, APIs enabled
#   - service account outreach-worker@ with secretAccessor on google-signin-token
#   - default compute account granted roles/cloudbuild.builds.builder (builds from source)
#   - service account outreach-scheduler@ with run.invoker; Scheduler job outreach-check (paused)
#   - 2026-09-28: Scheduler job outreach-sync, every 10 minutes, POST /jobs/sync
#
# The new revision serves NOTHING until traffic is moved to it: the scheduled sync keeps
# running on the revision that serves now. Test the new one on its tag first (a POST needs
# -d '' or Google's front end answers 411):
#   curl -X POST -d '' -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
#     "https://next---outreach-worker-z6borhtwoq-uc.a.run.app/jobs/sync?dry_run=1"
# then move traffic to it:
#   gcloud run services update-traffic outreach-worker --region=us-central1 \
#     --project=lakshyaa-outreach --to-tags=next=100
# Never set ENABLE_GMAIL_DRAFTS here: draft creation stays refused until the founder says so.
set -e
cd "$(dirname "$0")/.."
gcloud run deploy outreach-worker --source=. --region=us-central1 --project=lakshyaa-outreach \
  --service-account=outreach-worker@lakshyaa-outreach.iam.gserviceaccount.com \
  --no-allow-unauthenticated --max-instances=1 --concurrency=1 --timeout=600 --memory=1Gi \
  --set-secrets=GOOGLE_SIGNIN_TOKEN=google-signin-token:latest,TRACKING_KEY=tracking-signing-key:latest \
  --no-traffic --tag=next --quiet
