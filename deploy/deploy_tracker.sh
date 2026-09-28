#!/bin/sh
# Deploy the public tracker from the worker's newest image: the same code, run as the tracker
# (gunicorn outreach.tracker:app), as outreach-tracker@, with only the signing key.
#
# Public on purpose: it answers the tracking image and links in emails. The organisation allows
# only lakshyaa.ai accounts in IAM policies, so instead of granting allUsers this switches off
# the invoker check on this one service (--no-invoker-iam-check). The worker stays private.
# At most 3 instances, so a flood of hits cannot run up the bill.
set -e
P=lakshyaa-outreach
R=us-central1
IMAGE=$(gcloud run services describe outreach-worker --region=$R --project=$P \
  --format='value(spec.template.spec.containers[0].image)')
gcloud run deploy outreach-tracker --image="$IMAGE" --region=$R --project=$P \
  --service-account=outreach-tracker@$P.iam.gserviceaccount.com \
  --no-invoker-iam-check --max-instances=3 --concurrency=80 --timeout=15 \
  --set-secrets=TRACKING_KEY=tracking-signing-key:latest \
  --set-env-vars=TRACKING_ALLOWED_HOSTS=lakshyaa.ai \
  --command=gunicorn \
  --args=--bind=:8080,--workers=1,--threads=8,--timeout=15,--max-requests=500,--max-requests-jitter=100,outreach.tracker:app \
  --quiet
