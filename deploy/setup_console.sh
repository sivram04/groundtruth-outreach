#!/bin/sh
# One-time setup for the console (2026-09-28). Run from the repository root.
#
#   1. Google's sign-in gate (IAP) for Cloud Run, and its service agent.
#   2. The console's own service account, which may read the Google sign-in token and the
#      drafting settings, and nothing else.
#   3. The drafting settings in Secret Manager, from the local .secrets/pilot_handbook.json. The
#      console shows only the approval flags, the daily cap and the sending address from them.
#
# After the first deploy (deploy/deploy_console.sh), the two grants at the end let the gate call
# the service and let admin@lakshyaa.ai through the gate.
set -e
P=lakshyaa-outreach
R=us-central1
SA=outreach-console@$P.iam.gserviceaccount.com
NUMBER=$(gcloud projects describe $P --format='value(projectNumber)')

if [ "$1" != "after-deploy" ]; then
  # IAP, and Resource Manager, which `gcloud iap web add-iam-policy-binding` needs.
  gcloud services enable iap.googleapis.com cloudresourcemanager.googleapis.com --project=$P
  # IAP's service agent, service-NUMBER@gcp-sa-iap: what `gcloud beta services identity create`
  # does, called directly so the beta commands need not be installed.
  curl -s -f -X POST -H "Authorization: Bearer $(gcloud auth print-access-token)" \
    -H "Content-Length: 0" \
    "https://serviceusage.googleapis.com/v1beta1/projects/$NUMBER/services/iap.googleapis.com:generateServiceIdentity"
  echo
  gcloud iam service-accounts describe $SA --project=$P >/dev/null 2>&1 ||
    gcloud iam service-accounts create outreach-console --project=$P \
      --display-name="Outreach console: reads the leads Sheet"
  gcloud secrets add-iam-policy-binding google-signin-token --project=$P \
    --member=serviceAccount:$SA --role=roles/secretmanager.secretAccessor
  gcloud secrets describe outreach-settings --project=$P >/dev/null 2>&1 ||
    gcloud secrets create outreach-settings --project=$P --replication-policy=automatic \
      --data-file=.secrets/pilot_handbook.json
  gcloud secrets add-iam-policy-binding outreach-settings --project=$P \
    --member=serviceAccount:$SA --role=roles/secretmanager.secretAccessor
  # The assistant puts the founder's question, with the console's own data, to Gemini.
  gcloud projects add-iam-policy-binding $P --condition=None \
    --member=serviceAccount:$SA --role=roles/aiplatform.user
  exit 0
fi

gcloud run services add-iam-policy-binding outreach-console --region=$R --project=$P \
  --member=serviceAccount:service-$NUMBER@gcp-sa-iap.iam.gserviceaccount.com \
  --role=roles/run.invoker
gcloud iap web add-iam-policy-binding --project=$P --region=$R \
  --resource-type=cloud-run --service=outreach-console \
  --member=user:admin@lakshyaa.ai --role=roles/iap.httpsResourceAccessor
