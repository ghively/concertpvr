# concertpvr

YouTube concert & livestream PVR with Emby integration. Runs on Synology NAS via Docker.

**Current version:** v0.1.0 — see [`CHANGELOG.md`](CHANGELOG.md).

## Features

- **Buffer YouTube live streams** with configurable retention; scrub back through any captured fragment via the Timeline editor.
- **Schedule recordings** in advance (URL + start/end + optional artist tag).
- **Channel watchers** auto-record any matching live broadcast every 60 seconds.
- **Per-artist segmentation** from yt-dlp chapters, pasted setlists, or manual timeline marking.
- **Publish to Emby** — ffmpeg cuts the segment, generates `movie.nfo` + `poster.jpg` + `fanart.jpg`, drops it in your movies library, triggers a scan.
- **Single-password auth** for LAN deployments (optional — the app is open until you set a password from Settings).

## Status

All planned phases shipped. See [`docs/superpowers/specs/2026-04-24-concertpvr-design.md`](docs/superpowers/specs/2026-04-24-concertpvr-design.md) for the design spec and [`docs/superpowers/plans/`](docs/superpowers/plans/) for the per-phase implementation plans.

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
