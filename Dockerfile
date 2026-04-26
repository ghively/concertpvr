# syntax=docker/dockerfile:1.7

# ─── stage 1: build the react bundle ───
FROM node:20-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ─── stage 2: python runtime ───
FROM python:3.12-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg \
      ca-certificates \
      curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir .

# Sanity-check that yt-dlp installed correctly. Build fails fast if it didn't.
RUN yt-dlp --version

COPY src/ ./src/
COPY alembic.ini ./
COPY alembic/ ./alembic/

COPY --from=frontend /app/frontend/dist /app/static

ENV CPVR_DATA_DIR=/data
ENV CPVR_PUBLISH_DIR=/media/concerts
ENV CPVR_STATIC_DIR=/app/static
ENV CPVR_HOST=0.0.0.0
ENV CPVR_PORT=8787

VOLUME ["/data", "/media/concerts"]
EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -f http://localhost:8787/api/healthz || exit 1

CMD ["sh", "-c", "alembic upgrade head && python -m concertpvr"]
