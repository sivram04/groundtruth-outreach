FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY outreach ./outreach
CMD exec gunicorn --bind :$PORT --workers 1 --threads 1 --timeout 600 outreach.worker:app
