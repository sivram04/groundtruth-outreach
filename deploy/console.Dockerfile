# The console: the React pages, built with Vite, served with their data by the Python service.
# Built by deploy/deploy_console.sh through Cloud Build.
FROM node:24-slim AS pages
WORKDIR /console
COPY console/package.json console/package-lock.json ./
RUN npm ci
COPY console/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY outreach ./outreach
COPY --from=pages /console/dist ./console_dist
ENV CONSOLE_STATIC_DIR=/app/console_dist
# One process; its threads share one Sheets client, which the console reads under a lock.
# --max-requests replaces the process now and then, so nothing it keeps can grow for ever.
CMD exec gunicorn --bind :$PORT --workers 1 --threads 4 --timeout 60 --max-requests 500 --max-requests-jitter 100 outreach.console:app
