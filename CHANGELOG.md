# Changelog

## v0.1.0 — 2026-04-26

First release. Built across 6 implementation phases, all merged to main.

### Features

- **Buffer YouTube live streams** with rolling DVR-style retention. Per-stream subscription with optional title-filter regex and configurable retention days.
- **Schedule recordings** with explicit start/end windows. APScheduler fires 30s before start; recording runs until end time. Pending schedules are rehydrated on app restart.
- **Channel watchers** poll subscribed YouTube channels every 60 seconds via yt-dlp; auto-record any new live broadcast that matches the optional title filter.
- **Per-artist segmentation** with three sources: yt-dlp chapters (auto), pasted setlist (`Artist · hh:mm–hh:mm` lines), or manual timeline drag-create.
- **Publish to Emby** — ffmpeg cuts the segment with `-c copy`, generates `movie.nfo` + `poster.jpg` (Pillow-composited from a thumbnail) + `fanart.jpg`, places the bundle in your Emby movies library, calls `/Library/Media/Updated` to trigger a scan.
- **Optional password auth** (Argon2 hash + itsdangerous-signed session cookie). Open by default until you set a password from Settings.
- **Timeline editor** with vidstack player, custom region-bar timeline, and segment sidebar. Drag empty space to create, drag region body to slide, drag handles to resize. Keyboard shortcuts I / O for mark in/out.
- **Setlist paste modal** parses unicode em-dashes, ASCII hyphens, and "to" separators.
- **Library page** shows all published segments as a poster grid with artist/title filter.
- **Confirm dialogs** replace browser native `confirm()` across destructive actions.
- **Rotating log file** in `<data_dir>/logs/concertpvr.log` (5 MiB × 5 backups).

### Tech

- Backend: Python 3.12+, FastAPI, SQLAlchemy 2.0, Alembic, APScheduler, yt-dlp, ffmpeg, Pillow, argon2-cffi, itsdangerous.
- Frontend: React 18 + TypeScript + Vite, Tailwind, shadcn-style primitives, TanStack Query, vidstack, react-router-dom.
- Deployment: single multi-stage Docker image; SQLite for state; bind mounts for data and Emby library.

### Tests

177 backend tests passing. Frontend builds clean.

### Known limitations

- The Timeline editor only plays single-file recordings (scheduled outputs work; buffered fragment directories don't yet).
- Emby path translation between concertpvr's publish path and Emby's library path is not yet automatic — set both correctly in Settings.
- WebSocket auth: the `/ws/streams/{id}/progress` endpoint is open even after a password is set.
- Wavesurfer waveform: not yet integrated; the timeline strip is solid-color regions over a time axis.
- Frontend test suite: scaffolded but not authored. `npm test` runs Vitest with no test files.

See `docs/operations/troubleshooting.md` for runtime issue handling and `docs/release-checklist.md` for the manual smoke-test checklist.
