# Changelog

## v0.4.1 — 2026-05-05

Closes the four "Tier 3" deferred items from `jules.md` — every long-standing
TODO that was outside v0.4.0 scope is now implemented.

### Added — Like counts (Wave A)

- `probe_video_metadata` now also returns `like_count` alongside `view_count`
  in the slow-refresh path. The `BacklogItem` schema gains `like_count: int |
  None` and the backlog GET supports `sort=most_liked`. Frontend's
  BacklogBrowser exposes a "Most liked" sort chip and renders likes inline
  with views on each card. Items where YouTube hides the like count sort
  last (same pattern as `most_viewed`).

### Added — Auto Emby path translation (Wave B)

- New settings `emby_path_local_prefix` and `emby_path_emby_prefix`. When
  set, the publisher rewrites the on-disk path it sends to Emby's library
  refresh endpoint by swapping the local prefix for the Emby prefix. Lets
  concertpvr running in a Docker container talk correctly to an Emby that
  sees the same files at a different mount path (e.g., `/data/publish` →
  `/volume1/media/concerts`, or `/data/publish` → `Z:\Media\Concerts` for
  a Windows Emby host). Both null = pass-through; partial matches stay as-is.
- Settings UI gains two new path translation fields with explainer copy.

### Added — Setlist.fm integration (Wave C)

- New module `src/concertpvr/setlistfm.py` with `lookup_setlist(artist,
  date, *, api_key)` calling the setlist.fm REST API. Returns a normalized
  song list or `None` for "no match"; raises `SetlistFmError` on transport
  / 5xx failures.
- New per-watcher toggle `extract_setlist_from_setlistfm` and global
  setting `setlistfm_api_key`. The URL-paste flow runs setlist.fm as a
  fourth detection tier (after chapters, description, and comments) when
  both the API key and the per-watcher toggle are set. The toggle defaults
  to **off**; without an API key the tier is skipped regardless.

### Added — YouTube DVR-window scraping (Wave D)

- New endpoint `POST /api/streams/{id}/dvr-pull` (live streams only —
  rejects with 409 for `kind="video"`). Creates a Recording with status
  `vod_queued` and a filename prefix `dvr-…` that the queue handler reads
  as a discriminator to pass `--live-from-start` to yt-dlp. The download
  flows through the existing VOD pipeline; once complete it segments and
  publishes like any other VOD recording.
- `VodDownloader.download` gains a `live_from_start: bool` flag.
- Sources page exposes a "Pull DVR" button on each live stream row, with
  a confirm dialog that explains the constraint (only works while the
  broadcast is live and has a DVR window).

### Schema

- Migration `0010_emby_path_translation` — additive only:
  `settings.emby_path_local_prefix`, `settings.emby_path_emby_prefix`,
  `settings.setlistfm_api_key`, and `channel_watchers.extract_setlist_from_setlistfm`.

### Tests

- 24 new tests across 6 new files: `test_emby_path_translation`,
  `test_setlistfm`, `test_dvr_pull_api`, `test_vod_downloader_dvr`,
  `test_backlog_like_count`, `test_migration_0010`.
- Backend: 336 passed, 4 skipped. ruff/format/mypy clean. Frontend: tsc +
  vite build clean. Migration upgrade + downgrade verified.

---

## v0.4.0 — 2026-05-05

Wrap-up release closing the v0.3.4/v0.4 punch list from `jules.md`. Six
shippable features, no schema changes, 24 new tests (312 total).

### Added — VOD lifecycle controls

- **Cancel a running VOD download.** `POST /api/recordings/{id}/cancel`
  SIGTERMs the yt-dlp subprocess; the queue worker observes `VodCancelled`
  and writes a new terminal status `vod_cancelled`. Also handles
  `vod_queued` rows by skipping the handler when the worker pops them.
  Frontend exposes a Cancel button on `/recordings/vod` for both states.
- **Slow-refresh cancellation + resumption.** `POST
  /api/channel-watchers/{id}/backlog/refresh/cancel` flips a module-level
  flag the slow-refresh loop checks between batches; partial view-count
  progress is preserved as `cache.status='cancelled'`. Clicking Refresh
  again from that state resumes from where the user stopped — items that
  already have a `view_count` are skipped on the second pass. Frontend
  shows a Cancel button during fetching and a Resume banner when
  cancelled.
- **Most viewed sort chip restored.** Was added to the backend in v0.3.3
  but the frontend's `SortMode` had not been extended.

### Added — Library / publishing

- **Bulk-retry failed publishes.** `POST /api/segments/bulk-publish`
  accepts a list of `segment_ids` and continues past per-row failures,
  returning a per-segment status. Library page surfaces a banner when
  any publish_failed segments exist with a one-click retry.
- **Recording → Schedule reverse lookup.** `GET
  /api/recordings/{id}/schedule` returns the Schedule row that produced a
  given Recording (or `null` for ad-hoc recordings). Closes the v0.1
  limitation note without a migration; `Schedule.recording_id` was
  already indexed.

### Added — UX

- **Calendar grid view for the Schedule page.** Toggle between List and
  Calendar; preference persisted in `localStorage`. Month grid with
  prev/next/today nav, status-coloured event chips, and click-through to
  the existing detail panel. List view (the v0.3 grouped-by-day layout)
  is unchanged.

### Security

- **WebSocket auth gate.** `/ws/streams/{id}/progress` and
  `/ws/recordings/{id}/progress` now apply the same auth check as HTTP
  routes when a password is configured. Connections without a valid
  `cpvr_session` cookie are closed with policy code 1008. When no
  password is set, the endpoints remain open (matches HTTP behaviour).

### Fixed

- `VodCancelled` was double-defined (in `vod_queue` and `vod_downloader`)
  causing the queue worker's `except` to miss the exception raised from
  the downloader. Consolidated to a single class re-exported from
  `vod_queue`.

### Tests

- 24 new tests across six new files covering each shipped feature:
  `test_vod_queue_cancel`, `test_recordings_cancel_api`,
  `test_backlog_slow_refresh_cancel`, `test_ws_auth`,
  `test_recording_schedule_lookup`, `test_segments_bulk_publish`.
- Backend: 312 passed, 4 skipped (env-gated integration). ruff/format/mypy
  clean. Frontend: tsc + vite build clean.

### No schema changes

Migration count stays at 9 (0001…0009).

---

## v0.3.3 — 2026-04-27

Bug sweep + Most viewed backlog sort.

### Fixed (audit findings on v0.3.2)

- VOD `auto_publish_after_download` now wires through to the publisher
  on `complete` transitions. The toggle was previously persisted but
  inert.
- Frontend↔backend field-name drift: `Stream.upload_date` aligned to
  backend's `original_upload_date`; `ProbePlaylistItem` aligned to
  `youtube_id`/`channel_name` (was `video_id`/`channel`). The
  PostDownloadReview screen and the playlist-paste selection flow now
  function correctly.
- Sources page VOD rows show correct status (was checking impossible
  `recording`/`failed` statuses for `kind="video"`).
- Recordings page drops the dead `failed` filter chip (live path emits
  only `complete`/`interrupted`).
- Library year filter actually filters by year — `original_upload_date`
  now exposed on `SegmentRead`.
- Backlog Cancel button — endpoint implemented (was 404ing silently).
- Three silent-fail catches in BacklogBrowser now surface errors via
  toast.
- ffprobe failures in `_vod_handler` now log instead of swallow.
- Setlist comments-detection now runs on URL paste when the
  corresponding watcher has the toggle on (was watcher-poller-only).

### Added

- **Most viewed** backlog sort chip (deferred from v0.3.2). Requires an
  opt-in: tick "Include view counts (slower)" before clicking Refresh.
  Backend runs a per-video probe loop in batches of 20 with progress
  reporting. Videos with no public view count sort last.

### Refactored

- Status badges consolidated into a shared `STATUS_META` mapping —
  eliminates parallel `STATUS_COLOR` / `STATUS_BADGE` shapes that
  needed updating in two places.

### No schema changes

Migration count stays at 9 (0001…0009).

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
