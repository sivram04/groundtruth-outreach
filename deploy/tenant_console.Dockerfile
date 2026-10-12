# The multi-tenant console: the React pages (tenant-console/), built with Vite, served with
# their data by the Python service (outreach/tenant_console.py). Built by
# deploy/deploy_tenant_console.sh through Cloud Build.
#
# Unlike deploy/console.Dockerfile (the single-tenant console), this image installs
# requirements-tenant.txt too - psycopg, google-cloud-kms, google-crc32c - since this service
# actually talks to the tenant Postgres database and Cloud KMS, which the single-tenant console
# never does.
FROM node:24-slim AS pages
WORKDIR /console
COPY tenant-console/package.json tenant-console/package-lock.json ./
RUN npm ci
COPY tenant-console/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt requirements-tenant.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-tenant.txt
COPY outreach ./outreach
COPY --from=pages /console/dist ./tenant-console_dist
ENV TENANT_CONSOLE_STATIC_DIR=/app/tenant-console_dist
# One process; its threads share one DB connection pool implicitly via a fresh connection per
# request (outreach/tenant_console.py's _with_conn). --max-requests replaces the process now and
# then, so nothing it keeps can grow for ever.
CMD exec gunicorn --bind :$PORT --workers 1 --threads 4 --timeout 60 --max-requests 500 --max-requests-jitter 100 outreach.tenant_console:app
