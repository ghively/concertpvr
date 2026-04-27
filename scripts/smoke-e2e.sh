#!/usr/bin/env bash
# End-to-end smoke: paste URL → download → segment → publish → verify Emby
# bundle on disk. Hits the real network and a real video. Run before tagging.
#
# Requires: docker compose, curl, python (for JSON parsing — uses the project venv).
# Usage: bash scripts/smoke-e2e.sh
# Exits 0 on full pass, 1 with "FAILED AT STEP N: <reason>" on first failure.

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Pick a python; prefer the project venv.
if [ -x "./.venv/Scripts/python.exe" ]; then
    PY="./.venv/Scripts/python.exe"
elif command -v python3 >/dev/null 2>&1; then
    PY="python3"
else
    PY="python"
fi

# Mini jq replacement: jqp '.path.to.field' < input
jqp() {
    "$PY" -c "import json,sys
d = json.load(sys.stdin)
keys = '$1'.lstrip('.').split('.')
for k in keys:
    if k.endswith(']'):
        idx = int(k[k.index('[')+1:-1])
        k = k[:k.index('[')]
        d = d[k][idx] if k else d[idx]
    else:
        d = d[k] if isinstance(d, dict) else d
print(d if d is not None else '')"
}

API="http://127.0.0.1:8787/api"
TEST_URL="https://www.youtube.com/watch?v=dQw4w9WgXcQ"
TEST_YOUTUBE_ID="dQw4w9WgXcQ"
DEADLINE_DOWNLOAD=300   # 5 min cap on download
DEADLINE_PUBLISH=120    # 2 min cap on publish

fail() {
    echo "FAILED AT STEP $1: $2"
    docker logs concertpvr-dev 2>&1 | tail -30
    exit 1
}

# --- step 0: clean slate ---
echo "=== step 0: clean container + fresh DB ==="
docker compose -f docker-compose.dev.yml down >/dev/null 2>&1 || true
rm -f .local-data/metadata.db
rm -rf .local-publish/*
docker compose -f docker-compose.dev.yml up -d >/dev/null 2>&1
for i in $(seq 1 30); do
    if curl -sf -m 2 "$API/healthz" >/dev/null 2>&1; then break; fi
    sleep 2
done
curl -sf -m 2 "$API/healthz" >/dev/null || fail 0 "healthcheck never green"

# --- step 1: post URL ---
echo "=== step 1: POST /api/streams with $TEST_URL ==="
RESP=$(curl -sf -m 30 -X POST "$API/streams" -H "Content-Type: application/json" \
    -d "{\"url\":\"$TEST_URL\"}") || fail 1 "POST /streams failed"
STREAM_ID=$(echo "$RESP" | jqp .id)
[ -n "$STREAM_ID" ] && [ "$STREAM_ID" != "null" ] || fail 1 "no stream id in response: $RESP"
echo "  stream_id=$STREAM_ID"

# --- step 2: find the recording row created by the queue handler ---
echo "=== step 2: locate Recording row ==="
sleep 2
REC_ID=$(curl -sf "$API/recordings?stream_id=$STREAM_ID" | jqp '.[0].id')
[ -n "$REC_ID" ] && [ "$REC_ID" != "null" ] || fail 2 "no recording for stream $STREAM_ID"
echo "  recording_id=$REC_ID"

# --- step 3: poll until status=complete ---
echo "=== step 3: poll until vod_downloading -> complete (max ${DEADLINE_DOWNLOAD}s) ==="
START=$(date +%s)
while true; do
    NOW=$(date +%s)
    if [ $((NOW - START)) -gt $DEADLINE_DOWNLOAD ]; then
        STATUS=$(curl -sf "$API/recordings/$REC_ID" | jqp .status)
        ERROR=$(curl -sf "$API/recordings/$REC_ID" | jqp .error)
        fail 3 "download timed out after ${DEADLINE_DOWNLOAD}s (status=$STATUS, error=$ERROR)"
    fi
    STATUS=$(curl -sf "$API/recordings/$REC_ID" | jqp .status)
    case "$STATUS" in
        complete) echo "  complete after $((NOW - START))s"; break ;;
        vod_failed) fail 3 "recording status=vod_failed: $(curl -sf "$API/recordings/$REC_ID" | jqp .error)" ;;
        vod_queued|vod_downloading) ;;
        *) fail 3 "unexpected status $STATUS" ;;
    esac
    sleep 5
done

# --- step 4: verify file on disk ---
echo "=== step 4: verify staging file ==="
PATH_ON_DISK=$(curl -sf "$API/recordings/$REC_ID" | jqp .path)
# Container path /data/staging/... maps to local .local-data/staging/...
LOCAL_PATH=$(echo "$PATH_ON_DISK" | sed 's|^/data|.local-data|')
if [ ! -f "$LOCAL_PATH" ]; then
    # Path may have %(ext)s template OR yt-dlp picked a different extension.
    # Look for any matching file in the staging dir.
    MATCH=$(ls -1 .local-data/staging/ 2>/dev/null | grep -i "$TEST_YOUTUBE_ID" | head -1)
    [ -n "$MATCH" ] || fail 4 "no file matching $TEST_YOUTUBE_ID in .local-data/staging/ (recorded path: $PATH_ON_DISK)"
    LOCAL_PATH=".local-data/staging/$MATCH"
fi
SIZE=$(stat -c%s "$LOCAL_PATH" 2>/dev/null || stat -f%z "$LOCAL_PATH" 2>/dev/null)
[ "$SIZE" -gt 1000000 ] || fail 4 "staging file too small ($SIZE bytes): $LOCAL_PATH"
echo "  $LOCAL_PATH ($SIZE bytes)"

# --- step 5: create a segment ---
echo "=== step 5: POST /api/segments ==="
SEG_RESP=$(curl -sf -m 10 -X POST "$API/segments" -H "Content-Type: application/json" -d "{
    \"recording_id\": $REC_ID,
    \"artist\": \"Rick Astley\",
    \"title\": \"Never Gonna Give You Up\",
    \"start_s\": 0,
    \"end_s\": 30,
    \"source\": \"manual\",
    \"genres\": \"Pop, 80s\"
}") || fail 5 "POST /segments failed"
SEG_ID=$(echo "$SEG_RESP" | jqp .id)
[ -n "$SEG_ID" ] && [ "$SEG_ID" != "null" ] || fail 5 "no segment id: $SEG_RESP"
echo "  segment_id=$SEG_ID"

# --- step 6: publish ---
echo "=== step 6: POST /api/segments/$SEG_ID/publish ==="
curl -sf -m 10 -X POST "$API/segments/$SEG_ID/publish" >/dev/null || fail 6 "publish call failed"

# --- step 7: poll until segment is published ---
echo "=== step 7: poll segment until published (max ${DEADLINE_PUBLISH}s) ==="
START=$(date +%s)
while true; do
    NOW=$(date +%s)
    if [ $((NOW - START)) -gt $DEADLINE_PUBLISH ]; then
        STATUS=$(curl -sf "$API/segments/$SEG_ID" | jqp .status)
        fail 7 "publish timed out (status=$STATUS)"
    fi
    STATUS=$(curl -sf "$API/segments/$SEG_ID" | jqp .status)
    case "$STATUS" in
        published) echo "  published after $((NOW - START))s"; break ;;
        publish_failed) fail 7 "segment status=publish_failed: $(curl -sf "$API/segments/$SEG_ID" | jqp .error)" ;;
        publishing|draft) ;;
        *) fail 7 "unexpected segment status $STATUS" ;;
    esac
    sleep 3
done

# --- step 8: verify Emby bundle on disk ---
echo "=== step 8: verify Emby bundle ==="
EMBY_PATH=$(curl -sf "$API/segments/$SEG_ID" | jqp .emby_path)
[ -n "$EMBY_PATH" ] && [ "$EMBY_PATH" != "null" ] || fail 8 "no emby_path on segment"
LOCAL_EMBY_PATH=$(echo "$EMBY_PATH" | sed 's|^/media/concerts|.local-publish|')
[ -d "$LOCAL_EMBY_PATH" ] || fail 8 "emby dir missing: $LOCAL_EMBY_PATH"
[ -f "$LOCAL_EMBY_PATH/movie.nfo" ] || fail 8 "movie.nfo missing in $LOCAL_EMBY_PATH"
[ -f "$LOCAL_EMBY_PATH/poster.jpg" ] || fail 8 "poster.jpg missing"
[ -f "$LOCAL_EMBY_PATH/fanart.jpg" ] || fail 8 "fanart.jpg missing"
ls -1 "$LOCAL_EMBY_PATH"/*.mkv "$LOCAL_EMBY_PATH"/*.mp4 "$LOCAL_EMBY_PATH"/*.webm 2>/dev/null | head -1 >/dev/null || fail 8 "no movie file in $LOCAL_EMBY_PATH"
echo "  $LOCAL_EMBY_PATH"

# --- step 9: NFO content checks ---
echo "=== step 9: NFO has expected v0.3 elements ==="
NFO=$(cat "$LOCAL_EMBY_PATH/movie.nfo")
echo "$NFO" | grep -q "<title>Rick Astley" || fail 9 "<title>Rick Astley...</title> missing in NFO"
echo "$NFO" | grep -q "<genre>Pop</genre>" || fail 9 "<genre>Pop</genre> missing — v0.3 genres regression"
echo "$NFO" | grep -q "<genre>80s</genre>" || fail 9 "<genre>80s</genre> missing"
echo "$NFO" | grep -q "<year>" || fail 9 "<year> missing"

echo ""
echo "PASS: end-to-end VOD smoke complete"
echo "  stream_id=$STREAM_ID, recording_id=$REC_ID, segment_id=$SEG_ID"
echo "  staging file: $LOCAL_PATH"
echo "  emby bundle:  $LOCAL_EMBY_PATH"
exit 0
