# Changelog

## v0.2.0 — 2026-04-26

### Reliability

- Pool-at-capacity now returns HTTP 507 (was 500); UI disables the "Start buffer" button when full.
- Crashed mid-record? On restart, orphaned `recording`-status rows are marked `interrupted` automatically.
- `folder_pattern` setting is validated on save (rejects `{invalid_token}`); publisher catches any leftover bad patterns and marks the segment `publish_failed` instead of crashing.
- `session_secret` is generated eagerly at boot — eliminates a tiny race window during password set.
- Publisher's UTC-year fallback no longer uses local time.

### Performance

- Library page now makes a single `/api/segments?status=published` call instead of N+1 per recording.
- Index added on `schedules.recording_id`.

### API

- `GET /api/recordings` and `GET /api/segments` now accept `?status=...` to filter.
- All list endpoints (`/api/streams`, `/api/recordings`, `/api/segments`, `/api/schedules`) accept optional `?limit=N&offset=M`. Default unchanged (unlimited).

### UX

- Saving indicator appears next to a segment when its time edit is in flight.
- Dashboard "Recording now" stat shows fraction (e.g. "2/4").

### Build

- Dockerfile sanity-checks `yt-dlp` install during build.

### Resolved from v0.1.1 audit

All 12 items from the v0.1.1 audit are addressed. The "Recording → Schedule reverse lookup" item is still deferred (would require a migration to add `schedule_id` to recordings); workaround documented in `docs/operations/troubleshooting.md`.

---

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

- The Timeline editor only plays single-file recordings (scheduled outputs work; buffered fragment directories don't yet — concatenate manually per the troubleshooting guide).
- **YouTube DVR-window scraping is not implemented.** The spec called for "best-effort YouTube DVR-window seek" alongside the local rolling buffer. Only the local buffer is shipped — you can scrub through fragments concertpvr captured itself, but you can't reach into YouTube's own DVR window for content concertpvr didn't buffer.
- Emby path translation between concertpvr's publish path and Emby's library path is not yet automatic — set both correctly in Settings.
- WebSocket auth: the `/ws/streams/{id}/progress` endpoint is open even after a password is set.
- Wavesurfer waveform: not yet integrated; the timeline strip is solid-color regions over a time axis.
- Recording → Schedule reverse lookup: `Recording` rows don't carry a `schedule_id` field. To find "which schedule created this recording?", query `/api/schedules` and match by `recording_id`.
- Frontend test suite: scaffolded but not authored. `npm test` runs Vitest with no test files.

See `docs/operations/troubleshooting.md` for runtime issue handling and `docs/release-checklist.md` for the manual smoke-test checklist.
