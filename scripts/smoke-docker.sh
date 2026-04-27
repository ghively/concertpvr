#!/usr/bin/env bash
# Docker build + healthcheck smoke. Catches Dockerfile drift like the v0.3
# `src/` ordering bug. Run before tagging a release.
#
# Usage: bash scripts/smoke-docker.sh
# Exits 0 on full pass, 1 on first failure.

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "=== smoke-docker: build ==="
if ! docker compose -f docker-compose.dev.yml build; then
    echo "FAIL: docker build"
    exit 1
fi

echo "=== smoke-docker: up ==="
docker compose -f docker-compose.dev.yml down >/dev/null 2>&1 || true
if ! docker compose -f docker-compose.dev.yml up -d; then
    echo "FAIL: docker compose up"
    exit 1
fi

echo "=== smoke-docker: healthcheck (60s timeout) ==="
HEALTHY=0
for i in $(seq 1 30); do
    if curl -sf -m 2 http://127.0.0.1:8787/api/healthz >/dev/null 2>&1; then
        HEALTHY=1
        echo "  healthy after ${i}*2s"
        break
    fi
    sleep 2
done

if [ "$HEALTHY" != "1" ]; then
    echo "FAIL: healthcheck never returned 200"
    docker logs concertpvr-dev 2>&1 | tail -30
    docker compose -f docker-compose.dev.yml down >/dev/null 2>&1 || true
    exit 1
fi

echo "=== smoke-docker: error scan ==="
ERROR_COUNT=$(docker logs concertpvr-dev 2>&1 | grep -ciE "(^|\s)ERROR(\s|$)" || true)
if [ "$ERROR_COUNT" -gt 0 ]; then
    echo "FAIL: $ERROR_COUNT ERROR line(s) in container logs:"
    docker logs concertpvr-dev 2>&1 | grep -iE "(^|\s)ERROR(\s|$)" | head -10
    docker compose -f docker-compose.dev.yml down >/dev/null 2>&1 || true
    exit 1
fi

echo "=== smoke-docker: down ==="
docker compose -f docker-compose.dev.yml down >/dev/null 2>&1 || true

echo "PASS: docker build + healthcheck + clean log scan"
exit 0
