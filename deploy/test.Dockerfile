# Runs the test suite in a clean container, the same Python as the Cloud Run image.
#   docker build -f deploy/test.Dockerfile -t outreach-tests . && docker run --rm --network none outreach-tests
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt pytest
COPY outreach ./outreach
COPY examples ./examples
COPY tools ./tools
COPY tests ./tests
CMD ["python", "-m", "pytest", "-q", "tests"]
