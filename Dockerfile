# One service: FastAPI serves the API, the webhook and the built frontend at /.
# Stage 1 builds frontend/dist if a frontend exists (otherwise produces an empty dir).
FROM node:20-slim AS frontend
WORKDIR /src
COPY . .
RUN if [ -f frontend/package.json ]; then \
      cd frontend && (npm ci || npm install) && npm run build; \
    else mkdir -p frontend/dist; fi

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 DEMO_MODE=1
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements*.txt backend/
RUN pip install -r backend/requirements.txt && \
    if [ -f backend/requirements-agent.txt ]; then pip install -r backend/requirements-agent.txt; fi
COPY backend backend
COPY data data
COPY partners partners
COPY --from=frontend /src/frontend/dist frontend/dist
WORKDIR /app/backend
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
