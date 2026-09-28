FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY outreach ./outreach
# --max-requests: the worker process is replaced after a few requests, so memory that any library
# keeps between runs is given back (the deployed worker once grew to its limit and was killed).
CMD exec gunicorn --bind :$PORT --workers 1 --threads 1 --timeout 600 --max-requests 6 --max-requests-jitter 2 outreach.worker:app
