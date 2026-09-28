#!/bin/sh
# Stage 5 one-time setup (run 2026-09-28 on the founder's go). Each service gets only what it needs:
#   - the signing key, generated here and sent straight to Secret Manager: never printed or saved
#   - the queue: topic outreach-tracking-hits, pull subscription outreach-tracking-worker
#   - outreach-tracker@: may publish to the topic and read the key; nothing else (no mailbox,
#     no Sheet)
#   - outreach-worker@: may pull from the subscription and read the key
set -e
P=lakshyaa-outreach
TRACKER=outreach-tracker@$P.iam.gserviceaccount.com
WORKER=outreach-worker@$P.iam.gserviceaccount.com

python -c "import secrets; print(secrets.token_hex(32), end='')" |
  gcloud secrets create tracking-signing-key --project=$P --replication-policy=automatic --data-file=-

gcloud pubsub topics create outreach-tracking-hits --project=$P
gcloud pubsub subscriptions create outreach-tracking-worker --project=$P \
  --topic=outreach-tracking-hits --ack-deadline=60 --message-retention-duration=7d

gcloud iam service-accounts create outreach-tracker --project=$P \
  --display-name="Outreach tracker: public, publish only"
gcloud pubsub topics add-iam-policy-binding outreach-tracking-hits --project=$P \
  --member=serviceAccount:$TRACKER --role=roles/pubsub.publisher
gcloud secrets add-iam-policy-binding tracking-signing-key --project=$P \
  --member=serviceAccount:$TRACKER --role=roles/secretmanager.secretAccessor

gcloud pubsub subscriptions add-iam-policy-binding outreach-tracking-worker --project=$P \
  --member=serviceAccount:$WORKER --role=roles/pubsub.subscriber
gcloud secrets add-iam-policy-binding tracking-signing-key --project=$P \
  --member=serviceAccount:$WORKER --role=roles/secretmanager.secretAccessor
