# concertpvr — Design Spec

**Date:** 2026-04-24
**Author:** Brainstormed with Claude (Opus 4.7)
**Status:** Approved; ready for implementation plan

## 1. Overview

`concertpvr` is a personal PVR ("personal video recorder") for YouTube concerts and livestreams. It runs as a single Docker container on a Synology NAS, exposes a web UI, records live YouTube streams via `yt-dlp`, lets the user scrub and split long multi-artist recordings into per-artist clips, and publishes each clip as a discrete movie into an Emby library with proper metadata (NFO, poster, fanart).

The product exists because no off-the-shelf tool combines (a) reliable DVR-style buffering of YouTube livestreams, (b) per-artist segmentation of long festival broadcasts, and (c) Emby-compatible library publishing.

## 2. Goals & Non-Goals

### Goals

- Capture any YouTube livestream to disk with a rolling DVR buffer.
- Schedule recordings of specific time windows on live streams.
- Auto-record when subscribed YouTube channels go live (title-filterable).
- Split long recordings into per-artist segments using (in order): embedded chapters, user-entered setlist, manual timeline markers.
- Publish each segment as an Emby-recognized movie — directory structure, `movie.nfo`, poster, fanart — then trigger Emby library scan.
- Scrub backward through both (a) local buffered content and (b) YouTube's live DVR window (best-effort).
- Survive restart: in-progress recordings, scheduled jobs, and partial segmenting state all persist.

### Non-Goals

- Not a general-purpose YouTube downloader (a `yt-dlp` front-end for arbitrary VODs). Stick to the concert/live-performance use case.
- Not a video editor beyond start/end-time cutting and metadata. No effects, no transitions, no re-encoding beyond what ffmpeg `-c copy` can do.
- Not a transcoder. Record in YouTube's delivered format; let Emby handle playback transcoding.
- Not multi-user. Single shared password; trusted LAN. No user accounts, no per-user libraries.
- Not mobile-first. Desktop web UI. Usable on tablet; not optimized for phones.

## 3. Architecture

Single Docker container, single Python process, React SPA served from the same FastAPI app.

```
┌──────────────────────── concertpvr container ─────────────────────────┐
│                                                                       │
│   FastAPI (Uvicorn, asyncio)                                          │
│   ├── HTTP API  /api/*           (CRUD, WebSockets for progress)      │
│   ├── Static    /                (built React bundle)                 │
│   ├── APScheduler (AsyncIOScheduler, SQLAlchemy jobstore)             │
│   └── Worker pool (asyncio.Semaphore, default max 4 concurrent)       │
│                                                                       │
│   Domain modules (src/concertpvr/):                                   │
│     recorder.py    — yt-dlp subprocess lifecycle                      │
│     buffer.py      — rolling DVR buffer + retention pruner            │
│     scheduler.py   — schedule rows <-> APScheduler jobs               │
│     segmenter.py   — chapters + setlist + manual cut resolution       │
│     ffmpeg.py      — split, thumbnail, probe                          │
│     metadata.py    — NFO, poster/fanart generation                    │
│     emby.py        — publish-to-library, refresh-scan API             │
│     channels.py    — poll watched channels for go-live                │
│     dvrscrape.py   — best-effort YouTube DVR-window seek              │
│                                                                       │
│   SQLite (metadata.db)  ←→  SQLAlchemy + Alembic                      │
│                                                                       │
└──────────────┬─────────────────────────────┬──────────────────────────┘
               │ bind mounts                  │
               ▼                              ▼
   /volume1/concertpvr/                /volume1/media/concerts/
     buffer/   staging/   logs/   db     (Emby movies library)
```

### Process model

- **One Python process.** `yt-dlp` and `ffmpeg` are invoked as subprocesses (isolation for the only components that realistically crash).
- **asyncio throughout.** Recording workers are asyncio tasks that supervise subprocesses and stream progress via WebSockets.
- **APScheduler AsyncIOScheduler** shares the event loop and persists jobs in the same SQLite database, so job state survives restart.

### Storage layout

```
/volume1/concertpvr/
  buffer/{stream_id}/*.ts         rolling DVR fragments
  staging/{recording_id}.mkv      finished recordings pre-publish
  staging/{segment_id}/           per-segment work dir (NFO, poster, cut file)
  logs/{YYYY-MM-DD}.log           rotated daily
  metadata.db                     SQLite + SQLAlchemy schema

/volume1/media/concerts/
  {Artist} - {Festival} ({Year})/
    {Artist} - {Festival} ({Year}).mkv
    movie.nfo
    poster.jpg
    fanart.jpg
```

The Emby publish path is configurable; `{folder_pattern}` in settings accepts `{artist}`, `{festival}`, `{venue}`, `{year}`, `{date}`, `{title}`.

## 4. Tech Stack

### Backend
- **Python 3.12**
- **FastAPI** (HTTP + WebSockets)
- **Uvicorn** (ASGI server)
- **Pydantic v2** (request/response + settings)
- **SQLAlchemy 2.0** + **Alembic** (migrations)
- **SQLite** (metadata.db)
- **APScheduler 3.x** (AsyncIOScheduler with SQLAlchemyJobStore)
- **yt-dlp** (as a Python library where practical; subprocess for recording jobs)
- **ffmpeg** (subprocess)

### Frontend
- **React 18** + **TypeScript** + **Vite**
- **Tailwind** + **shadcn/ui**
- **TanStack Query** (server state)
- **vidstack** (video player)
- **wavesurfer.js** + regions plugin (waveform timeline)
- **dnd-kit** (drag-and-drop for timeline region editing and setlist reordering)

### Packaging
- **Single Docker image** (multi-stage: node build → python runtime with `/static` baked in)
- **docker-compose.yml** with bind mounts for `/volume1/concertpvr/` and `/volume1/media/concerts/`
- One exposed port (default 8787)

## 5. Data Model (SQLite)

```
streams
  id, kind {channel, video, live}, youtube_id, url,
  title, channel_name, thumbnail_url, added_at

watch_subscriptions   -- "buffer this live URL" flag
  id, stream_id (FK), enabled, title_filter (regex, nullable),
  quality_cap (string, nullable), retention_days

schedules
  id, stream_id (FK), starts_at, ends_at, artist (nullable),
  status {pending, running, complete, failed, cancelled},
  error (nullable), recording_id (FK, nullable)

recordings
  id, stream_id (FK), schedule_id (FK, nullable), started_at, ended_at,
  path, duration_s, size_bytes, width, height, fps,
  status {recording, complete, failed, interrupted},
  is_buffer (bool), raw_chapters_json (nullable)

segments
  id, recording_id (FK), artist, title (nullable),
  start_s, end_s, source {chapter, setlist, manual},
  status {draft, publishing, published, publish_failed},
  emby_path (nullable), error (nullable),
  poster_path (nullable), nfo_path (nullable)

setlists
  id, recording_id (FK), artist, start_s, end_s
  -- times relative to recording start, same convention as segments

channel_watchers
  id, channel_id, channel_name, title_filter (regex, nullable),
  quality_cap (nullable), retention_days, enabled,
  last_polled, last_live_id (nullable)

settings  -- singleton; one row
  emby_url, emby_api_key, emby_library_path, publish_root,
  buffer_root, staging_root, folder_pattern,
  password_hash, session_secret,
  default_quality, default_retention_days,
  max_concurrent_recordings, auto_prune_when_full,
  yt_dlp_cookies_path (nullable)
```

Relationships: one `recording` → many `segments`; one `stream` → many `recordings`, `schedules`, optionally one `watch_subscription`.

## 6. Core Flows

### Flow A — Rolling DVR buffer

1. User POSTs a live URL → `POST /api/streams` (`kind=live`) creates the row.
2. User toggles "Buffer this" → creates `watch_subscription`; recorder spawns yt-dlp with `--live-from-start --hls-prefer-native -f <quality> -o /buffer/{stream_id}/%(epoch)s.ts`.
3. Frontend opens WebSocket `/ws/streams/{id}/progress` — receives `{bytes, bitrate, duration_s, bufferDepth_s}` frames.
4. Retention worker (APScheduler, every 5 min) deletes fragments older than `retention_days` per subscription.
5. User scrubs back: UI plays `/buffer/{stream_id}/` as a playlist via vidstack. Dragging wavesurfer region + "Save segment" → `POST /api/segments {recording_id, start_s, end_s, artist}` → creates draft segment.

### Flow B — Scheduled recording

1. `POST /api/schedules {stream_url, starts_at, ends_at, artist?}` → creates `streams` row if needed + `schedules` row; APScheduler adds job for `starts_at - 30s`.
2. Job fires → `recorder.start(schedule_id)` spawns yt-dlp writing to `/staging/{recording_id}.mkv`.
3. At `ends_at` → SIGTERM yt-dlp, mux-finalize, `recording.status=complete`, `schedule.status=complete`.
4. If `artist` was provided, auto-create one segment spanning the full recording with `source=manual`, status=`draft`; user publishes from the Library screen.

### Flow C — Multi-artist split + publish

1. On `recording.status=complete`, segmenter runs once:
   - If `raw_chapters_json` has entries → create `draft` segments with `source=chapter`.
   - Else if `setlists` rows exist for this recording → create `draft` segments with `source=setlist`.
   - Else → no auto-segments; user opens Timeline Editor to mark manually.
2. User reviews/adjusts in Timeline Editor; changes PATCH segments.
3. "Publish all" → for each draft segment:
   - `ffmpeg -ss A -to B -i in.mkv -c copy out.mkv` to staging folder.
   - `metadata.generate_nfo(segment)` → `movie.nfo`.
   - `metadata.generate_poster(segment)` → `poster.jpg` composited from recording thumbnail + text overlay (artist / festival / year).
   - `metadata.copy_fanart(recording)` → `fanart.jpg` (recording thumbnail).
   - Move folder into configured Emby path.
   - `emby.trigger_scan(path)` — POST to `/Library/Media/Updated` with that path.
   - Segment `status=published`, record `emby_path`.
4. Any failure → segment `status=publish_failed`; retry from UI.

### Flow D — Channel watcher

1. APScheduler runs `channels.poll_all()` every 60 s.
2. For each enabled `channel_watcher`, call `yt-dlp --flat-playlist --dump-json <channel>/streams` to enumerate currently-live broadcasts.
3. For each live broadcast not matching `last_live_id`:
   - If `title_filter` is set, reject non-matches.
   - Else create a `stream`, `recording`, and start recording immediately (no end time; recorder ends when YouTube marks the broadcast ended).
4. Update `last_live_id` + `last_polled`.

## 7. UI Screens

Style: **Studio Dark** (DaVinci/Premiere-like shell — dense, monospace timecodes, warm dark surfaces) + **editorial accent palette** (terracotta primary, sage for active/good, amber for timecodes/scheduled, muted purple for auto/watcher events).

Screens:

1. **Dashboard** — stat strip (recording now / scheduled today / published total / watchers active) + live recordings list with progress bars + "Up Next" rail.
2. **Streams** — toolbar (search, kind filter, status filter, ＋Add) + data table (favorite, title+URL, channel, kind, status, retention, actions).
3. **Timeline / Segment Editor** — *the centerpiece.* Vidstack player (top) + wavesurfer waveform with draggable colored regions per artist + playhead + bottom toolbar (Mark in/out, Snap-to-silence, Prev/Next, Play) + right rail segment list with source badge and publish status.
4. **Schedule** — week calendar view; color-coded events by source (scheduled/watcher/manual); click to edit; ＋New schedule button opens a modal.
5. **Library** — toolbar (search + filters) + 5-column poster grid of published segments; posters show duration + resolution badge and festival overlay.
6. **Channel Watchers** — list of watcher cards (channel avatar, name, last-live, title-filter regex pill, quality + retention, enable toggle).
7. **Setlist Entry (modal)** — repeatable rows of `[artist] [start hh:mm] [end hh:mm]`; supports paste-from-clipboard of `"Artist · hh:mm–hh:mm"` lines.
8. **Settings** — left-nav sections (Emby, Paths & Storage, Recording defaults, Security, yt-dlp, About); right pane shows fields with helper text.

### Key interactions

- Timeline editor is bidirectional: dragging a region edits the `segments` row; editing a row in the right rail moves the region.
- Drag-and-drop from Streams row to Schedule calendar creates a schedule.
- Global keyboard shortcut layer available in Timeline editor (`Space`, `I`, `O`, `,`, `.`).

## 8. Subagent Development Workflow

The user explicitly wants **Opus as orchestrator, Sonnet as coder, Haiku as cleanup auditor** to conserve tokens. This maps to:

### Roles

| Role | Model | Responsibilities |
|---|---|---|
| Orchestrator | Opus 4.7 | Reads spec + plan, dispatches tickets, reviews diff summaries, decides when to call auditor, handles integration between modules |
| Coder | Sonnet 4.6 | Implements one ticket end-to-end. Writes code + tests. Commits. |
| Cleanup auditor | Haiku 4.5 | Runs lint/format/type-check, removes dead code, fixes imports, simplifies obvious bloat, runs tests. |

### Token-conservation rules

1. **Orchestrator never reads application code directly.** It reads test summaries, diff summaries, file lists produced by coder/auditor.
2. **Each coder invocation is scoped to one ticket** with only: relevant spec section, module interface contract, file paths to read, and existing tests to pass. No whole-codebase context.
3. **Auditor receives only the diff** plus project lint config. Re-reads a full file only when a tool reports an error inside it.
4. **Parallel coder dispatch** for independent modules — `metadata.py` and `channels.py` don't interact, so they run simultaneously in separate coder invocations.

### Ticket contract

```
TICKET-NN: <module> — <one-sentence outcome>
Spec section: docs/superpowers/specs/2026-04-24-concertpvr-design.md#<anchor>
Files: src/concertpvr/<module>.py, tests/test_<module>.py
Interface: <exact function/class signatures>
Acceptance:
  - pytest tests/test_<module>.py -q passes
  - mypy src/concertpvr/<module>.py is clean
  - ruff src/concertpvr/<module>.py is clean
```

After coder commits:
- Orchestrator dispatches auditor against the commit's diff.
- Auditor may make style/cleanup commits but never changes behavior.

## 9. Error Handling & Resilience

### Subsystem-specific

- **yt-dlp failures:** capture exit code + stderr; mark `recording.status=failed` with the error; surface as retryable in the UI.
- **ffmpeg split failures:** fail just the segment; `segment.status=publish_failed`; leave sibling segments untouched.
- **Emby publish failures:** keep the staged file; `segment.status=publish_failed`; retry button in UI.
- **Channel polling network blip:** log, retry on next 60 s tick; never crash the scheduler.
- **Disk full:** reject new recordings with HTTP 507; show banner in UI. If `auto_prune_when_full=true`, prune oldest buffer fragments before failing.

### Cross-cutting

- All long-running state persisted in SQLite.
- APScheduler's SQLAlchemyJobStore means scheduled jobs survive restart.
- On startup: scan `/staging/` for orphan files whose `recordings.status=recording`; mark them `interrupted`; expose a "Resume" action if the underlying stream is still live.
- WebSockets automatically reconnect on the client; server re-sends last known state.

## 10. Testing Strategy

### Backend

- **Unit tests (pytest)** for every module. `yt-dlp` and `ffmpeg` mocked at the subprocess boundary via a thin `ProcessRunner` seam.
- **Integration test** for the record → segment → publish pipeline using a CC-licensed ~30-second clip checked into `tests/fixtures/`. Asserts final Emby folder structure, NFO contents, poster presence.
- **Schema tests** via Alembic upgrade/downgrade round-trip on an in-memory SQLite.

### Frontend

- **Vitest + React Testing Library** for components (timeline region math, form validation, WS reconnection hook).
- **Playwright** for one happy-path E2E: open Timeline editor for a fixture recording, drag a region, save, verify API call fired.

### Manual

One real-YouTube smoke test per release: tune a live stream, buffer 5 min, scrub, save a segment, publish. Non-automated. Documented in `docs/release-checklist.md`.

## 11. Deployment / Operations

### Image

Multi-stage Dockerfile:
1. `node:20-alpine` → build React SPA (`npm run build`) into `/dist`.
2. `python:3.12-slim` with `ffmpeg` + `yt-dlp` apt/pip installed → copy `/dist` into `/app/static`, `uvicorn concertpvr.main:app --host 0.0.0.0 --port 8787`.

### Compose example

```yaml
services:
  concertpvr:
    image: concertpvr:latest
    ports: ["8787:8787"]
    volumes:
      - /volume1/concertpvr:/data
      - /volume1/media/concerts:/media/concerts
    environment:
      CPVR_DATA_DIR: /data
      CPVR_PUBLISH_DIR: /media/concerts
      CPVR_EMBY_URL: http://emby:8096
      CPVR_EMBY_API_KEY_FILE: /run/secrets/emby_api_key
      CPVR_PASSWORD_FILE: /run/secrets/ui_password
    secrets: [emby_api_key, ui_password]
    restart: unless-stopped
```

### Defaults

- Max concurrent recordings: **4** (configurable).
- Default retention: **7 days** for buffered live, **keep forever** for scheduled.
- Default quality: `yt-dlp` `bestvideo*+bestaudio/best` with a configurable resolution cap.
- Auth: single shared password (argon2 hash in settings), LAN-only deployment assumed. Session cookie.

## 12. Open Questions

- **Exact Emby library location on this user's Synology** — defaults assumed `/volume1/media/concerts/`; confirm during first-run setup wizard.
- **Emby `Movies` vs `Concerts` library type** — Emby lets you label a library "concerts" but its metadata schema is the Movies one. Current plan: tell user to add the folder as a Movies library in Emby. OK to revisit if this proves awkward.
- **Best-effort YouTube DVR scrape** — the `dvrscrape.py` module is marked experimental; YouTube changes its HLS manifest handling frequently. Ship it disabled by default, enable via Settings.
- **Cookies for age-gated / member-only streams** — settings exposes a cookies.txt path; flow is "export from your browser, paste path in Settings." Documented in help text, not a first-class onboarding step.

---

*End of spec. Ready to hand off to `writing-plans` skill for implementation plan.*
