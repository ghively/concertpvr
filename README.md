# concertpvr

YouTube concert & livestream PVR with Emby integration. Runs on Synology NAS via Docker.

**Current version:** v0.4.1 — see [`CHANGELOG.md`](CHANGELOG.md).

## Features

### Live recording
- **Buffer YouTube live streams** with configurable retention; scrub back through any captured fragment via the Timeline editor.
- **Schedule recordings** in advance (URL + start/end + optional artist tag).
- **Channel watchers** auto-record any matching live broadcast every 60 seconds.

### VOD downloads (v0.3+)
- **Three workflows:** paste a single YouTube URL, subscribe to a channel for forward-only auto-pull, or ingest an entire playlist.
- **Whole-channel backlog browser** (v0.3.1) — full-channel cache lets you sort by longest / oldest / newest across thousands of videos and manually pick what to download. Auto-pull from subscriptions never queues backlog.
- **Setlist auto-detection** from YouTube chapters, description text, or top comments (opt-in per watcher).
- **Per-watcher artist regex** extracts artist from titles (`Khruangbin: Tiny Desk Concert` → `Khruangbin`). No match → manual review fallback.
- **Auto-publish** on trusted channels (off by default, explicit opt-in via the smart-paste modal).

### Library + publishing
- **Per-artist segmentation** from yt-dlp chapters, pasted setlists, or manual timeline marking.
- **Per-segment + per-watcher genres** flow into NFO `<genre>` elements.
- **Publish to Emby** — ffmpeg cuts the segment, generates `movie.nfo` + `poster.jpg` + `fanart.jpg`, drops it in your movies library, triggers a scan.
- **Source-file lifecycle** — manual or auto-delete after all segments published.

### Auth
- **Single-password auth** for LAN deployments (optional — the app is open until you set a password from Settings).

## Status

Active development. See [`CHANGELOG.md`](CHANGELOG.md) for shipped versions. Current track:

- `v0.3.0` — VOD downloads shipped (Tiny Desk / KEXP / NPR / playlists).
- `v0.3.1` — whole-channel backlog browse + VOD subscription safety + VOD progress UI shipped.
- `v0.3.2` — VOD parity pass: dedicated `/recordings/vod` page, dedicated components, smart-paste consent defaults.
- `v0.3.3` — VOD bug-sweep + Most viewed backlog sort (slow-refresh opt-in).
- `v0.4.0` — feature wrap-up: cancel-while-downloading, slow-refresh resume, calendar Schedule view, bulk-retry failed publishes, WebSocket auth, Recording → Schedule reverse lookup.
- `v0.4.1` — final long-tail features: like counts (Most liked sort), auto Emby path translation, setlist.fm integration, YouTube DVR-window scraping (`POST /streams/{id}/dvr-pull`).

## Audit harness

v0.3.0 introduced four regression-prevention layers:
- `tests/test_frontend_contracts.py` — every UI POST/PATCH payload validated against the backend Pydantic schema.
- `tests/integration/test_real_yt_dlp.py` — env-gated real-network probes (`CPVR_INTEGRATION_TESTS=1`).
- `scripts/smoke-docker.sh` — Docker build + healthcheck.
- `scripts/smoke-e2e.sh` — full URL → download → publish flow against a real video.

## Deployment (Synology, Docker)

```bash
docker compose up -d --build
```

The compose file expects two bind mounts:
- `/volume1/concertpvr` → app data (DB, buffer, staging, logs).
- `/volume1/media/concerts` → Emby movies library target.

Adjust paths to your Synology layout. The container runs `alembic upgrade head` on each start, so schema migrations apply automatically.

After first start, browse to `http://<your-nas-ip>:8787` and:
1. Open **Settings** → set a password (one-time; until you do, the app is open on your LAN).
2. Configure Emby URL + API key in **Settings** if you want library refreshes.
3. **Streams** → add a YouTube URL → start buffer; or **Schedule** → new schedule; or **Watchers** → add a channel.

## Operations

- [`docs/operations/environment.md`](docs/operations/environment.md) — full `CPVR_*` variable reference.
- [`docs/operations/troubleshooting.md`](docs/operations/troubleshooting.md) — common failure modes and fixes.
- [`docs/operations/cookies.md`](docs/operations/cookies.md) — exporting YouTube cookies for member-only / age-gated content.
- [`docs/operations/backup-and-restore.md`](docs/operations/backup-and-restore.md) — what's stateful and how to back it up.
- [`docs/release-checklist.md`](docs/release-checklist.md) — manual smoke-test checklist for new deployments.

## API

FastAPI auto-publishes the OpenAPI schema at:

- Swagger UI: `http://<host>:8787/docs`
- ReDoc: `http://<host>:8787/redoc`

When auth is enabled these endpoints still require a session cookie (login at `/login`).

## Local development

### Backend (one shell)

```bash
python -m venv .venv
source .venv/bin/activate    # or .venv/Scripts/activate on Windows
pip install -e ".[dev]"

export CPVR_DATA_DIR=/tmp/cpvr-dev
alembic upgrade head
python -m concertpvr
```

Backend at http://localhost:8787.

### Frontend (another shell)

```bash
cd frontend
npm install
npm run dev
```

Frontend at http://localhost:5173, proxying `/api/*` to the backend.

## Tests

```bash
pytest                       # backend (177 tests as of v0.1.0)
cd frontend && npm run typecheck && npm run build
```

The frontend test runner (Vitest) is configured but no component tests have been authored yet — `npm test` runs cleanly with zero tests.

## License

[MIT](LICENSE).
