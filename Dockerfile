# --- build the React app ---
FROM node:20-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- API (also serves the built frontend) ---
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
WORKDIR /app/backend
COPY backend/pyproject.toml ./
COPY backend/app ./app
COPY backend/evals ./evals
RUN pip install ".[queue,postgres]"
COPY --from=web /web/dist /app/frontend/dist

RUN useradd --create-home --uid 1000 app && mkdir -p /data && chown app /data
USER app
ENV DATABASE_URL=sqlite:////data/ticketpilot.db
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
