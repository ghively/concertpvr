# Changelog

## v0.3.2 — 2026-04-27

VOD parity pass. Closes the v0.3 spec gap that "VOD downloads is a peer
feature" rather than a special-case bolted onto live recordings.

### Frontend

- New `/recordings/vod` page — peer to `/recordings`, optimized for the
  download workflow with status filter chips and VOD-shaped action
  buttons (retry on failed, open review on complete, delete source after
  publish).
- New components: `VodQueueStrip` (top of `/recordings/vod` + Dashboard
  stat strip area) and `VodRecordingRow` (purpose-built for the VOD
  lifecycle). `LiveProgressBar` simplified to live-only — `VodProgressBar`
  handles VOD progress.
- Top nav gains a "VOD Downloads" entry between Recordings and Library.
  Recordings page narrows to live-only — VOD statuses move to the new page.
- Smart-paste channel subscribe: `watch_vod_uploads` defaults to **off**
  (was on). Each toggle gets explicit consent copy. Backlog browse stays
  manual-only with a callout.

### Backend

- `Recording` model docstring documents the two state machines explicitly
  (live: recording → complete | failed | interrupted; VOD: vod_queued →
  vod_downloading → complete | vod_failed). `failed` annotated as
  reserved (live-only, not currently emitted).
- New `tests/test_vod_workflow.py` — VOD-only end-to-end flow tests in a
  dedicated file (paste → queue → download → review → publish), mirrors
  `test_streams_api.py` for live but isolates the VOD lifecycle.

### Behavior changes

- Subscribing to a channel with `watch_vod_uploads=true` queues only
  uploads strictly *after* subscription date (forward-only — fixed in
  v0.3.1). v0.3.2 makes this explicit in the modal copy.

### Known deferrals to v0.3.3

- Backlog "Most viewed" sort chip was on the v0.3 spec but is deferred:
  yt-dlp flat-extract doesn't return `view_count`, so a per-video probe
  is required. Spec annotated; implementation revisits with an opt-in
  "Slow refresh" path.

### No schema changes

Migration count stays at 9 (0001…0009). v0.3.2 is a UX clarity pass, not
a structural change. ~286 backend tests passing, frontend builds clean,
Docker smoke green, e2e smoke green.

---

## v0.3.1 — 2026-04-27

Whole-channel backlog browse + VOD subscription safety + VOD progress UI.

### Backlog browse across the whole channel

- New `channel_backlog_cache` table (migration 0009) — per-watcher
  one-shot snapshot of the entire channel via flat-extract.
- `GET /api/channel-watchers/{id}/backlog` reads from cache; sort/filter
  /paginate runs against the WHOLE channel (was: only newest 50).
- New endpoints: `GET .../backlog/status` (poll) +
  `POST .../backlog/refresh` (async background fetch).
- Removed `most_viewed` sort option (yt-dlp flat-extract has no view counts).
- Frontend BacklogBrowser handles cache-empty / fetching / error states with
  polling + manual Refresh button.

### VOD subscription safety

- **Forward-only filter fix:** when subscribing to a channel with
  `watch_vod_uploads=true`, the previous filter let through any upload with
  null `upload_date` (common for older videos). Result: 20+ Tiny Desk
  videos auto-queued on subscription. Now: missing `upload_date` = skip,
  and same-day uploads (`<=`) are also skipped. Only strictly-future
  uploads get queued.
- Backlog browse remains metadata-only — guardrail test in
  `tests/test_backlog_cache.py` locks it in.

### VOD download progress

- New `/ws/recordings/{id}/progress` WebSocket endpoint subscribes to
  the broadcaster topic populated by the queue handler.
- New `VodProgressBar` component subscribes to that WS — shows live %, ETA,
  bytes/rate during download.
- Recordings page now uses `VodProgressBar` for `vod_downloading` rows
  (was using a broken determinate-mode escape hatch on `LiveProgressBar`).

### Other

- `playlist_ingest.expand_playlist` cap bumped 500 → 5000 (covers all
  realistic music playlists).
- Thumbnail null-fallback to YouTube canonical CDN URL
  (`https://i.ytimg.com/vi/{id}/mqdefault.jpg`) — every backlog item now
  always has a thumbnail.

---

## v0.3.0 — 2026-04-26

### Features

- **Download non-live YouTube performances.** Tiny Desk Concerts, KEXP sets, NPR Music Field Recordings — three workflows: paste any URL, subscribe to a channel for auto-pull, or ingest an entire playlist.
- **Channel watchers learn VOD mode.** Existing watchers gain "Watch for new VOD uploads" + "Auto-publish to Emby" toggles. Forward-only by default; backlog browser to manually pick old videos.
- **Setlist auto-detection.** Description text, YouTube chapters, and (opt-in, slower) pinned/top comments parsed for timestamped setlists. Detected setlists surface on the post-download review screen with apply/edit/dismiss.
- **Per-watcher artist regex.** Named-group regex pattern extracts artist from titles ("Khruangbin: Tiny Desk Concert" → "Khruangbin"). No match → safe fallback to manual review even if auto-publish is on.
- **Genres.** Per-watcher default genres + per-segment overrides + click-to-add suggestions from YouTube tags. Genre filter chips on Sources and Library pages. NFO emits one `<genre>` per genre.
- **Source-file lifecycle.** Per-recording manual delete button (gated on all segments published), plus per-watcher and global auto-delete-after-publish settings.

### API

- `POST /api/streams` — handles single video / channel / playlist URLs (smart-paste routing).
- `GET /api/channel-watchers/{id}/backlog` — paginated channel-videos listing with sort options.
- `POST /api/channel-watchers/{id}/backlog/download` — bulk-download selected backlog items.
- `POST /api/playlists/ingest` + `/confirm` — playlist preview and bulk-add.
- `POST /api/recordings/{id}/retry` — retry a failed VOD download.
- `DELETE /api/recordings/{id}/source` — manual source-file removal (409 if any segment is unpublished).
- `PATCH /api/channel-watchers/{id}` — accepts 9 new fields (live/VOD toggles, filters, regex, genres, auto-publish, auto-delete).

### Schema

- Migration `0008_vod_support` adds 20 columns across 5 tables (channel_watchers, streams, segments, recordings, settings). All additive — no drops, no renames, no type changes.

### UI

- Streams tab renamed to **Sources**; mixed live + video kinds with kind badges.
- "Add URL" smart-paste modal with three result modes (single video / channel / playlist).
- Watcher detail page extended: Settings tab with VOD filters/automation, Backlog tab with a multi-select cards grid.
- Post-download review screen for VODs at `/recordings/{id}/review`.
- Dashboard split-stat strip: Live + VODs as separate cards.
- Genre filter chips on Sources + Library; year filter on Library.
- Timeline editor segment sidebar gains genres autocomplete + YouTube-tag suggestion chips.

### Performance

- Separate VOD queue (default cap 2) — VOD downloads never starve the live recorder pool.
- Index on `streams.watcher_id` for the "From watcher" filter.

### Tests

72 new backend tests (191 v0.2 → 263 v0.3). Frontend builds clean.

### Known limitations

- Backlog tab title filter and duration sort only — yt-dlp's flat-extract doesn't return tag/genre data cheaply.
- "Most viewed" sort on backlog is documented but not yet wired (would require full probe per item).
- External setlist sources (setlist.fm) not yet integrated; documented as future enhancement.

---

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
