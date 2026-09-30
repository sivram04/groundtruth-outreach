# Frontend checks (vitest, type-check, build) in a clean Node container - never on the host.
#   docker build -f deploy/console-test.Dockerfile -t outreach-console-tests .
#   docker run --rm --network none outreach-console-tests
# Dependencies are installed at build time (needs network); the checks run with no network.
FROM node:20-slim
WORKDIR /app/console
COPY console/package.json console/package-lock.json ./
RUN npm ci
COPY console ./
CMD ["sh", "-c", "npm run test && npm run typecheck && npm run build"]
