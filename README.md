# concertpvr

YouTube concert & livestream PVR with Emby integration. Runs on Synology NAS via Docker.

## Status

**Phase 1 (Foundation) complete.** App boots, nav works, Settings page saves. No recording yet.

See the full roadmap and spec:
- Design: `docs/superpowers/specs/2026-04-24-concertpvr-design.md`
- Phase plans: `docs/superpowers/plans/`

## Local development

### Backend (one shell)

```bash
python -m venv .venv
source .venv/bin/activate   # or .venv/Scripts/activate on Windows
pip install -e ".[dev]"

export CPVR_DATA_DIR=/tmp/cpvr-dev   # Linux/Mac
# or: set CPVR_DATA_DIR=C:\tmp\cpvr-dev   (Windows cmd)

alembic upgrade head
python -m concertpvr
```

Backend now at http://localhost:8787.

### Frontend (another shell)

```bash
cd frontend
npm install
npm run dev
```

Frontend at http://localhost:5173, proxying `/api/*` to the backend.

## Tests

```bash
pytest                     # backend
cd frontend && npm test    # frontend (Vitest)
```

## Production (Docker)

```bash
docker compose up -d --build
```

The compose file expects:
- `/volume1/concertpvr` — runtime data (DB, buffer, staging, logs)
- `/volume1/media/concerts` — Emby movies library target

Adjust paths as needed for your Synology.

## License

TBD.
