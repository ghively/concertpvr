# VOD Downloads — Design Spec

**Date:** 2026-04-26
**Target version:** v0.3.0
**Baseline:** v0.2.0 (181 → 191 backend tests; concertpvr live + scheduled + channel-watcher PVR shipped)

> **Follow-on plans:**
> - `docs/superpowers/plans/2026-04-26-v0.3-audit.md` — diagnosis of integration gaps after the initial v0.3 ship.
> - `docs/superpowers/plans/2026-04-26-v0.3-audit-execution.md` — the audit + stabilization that landed in v0.3.0 final.
> - `docs/superpowers/plans/2026-04-26-vod-downloads.md` — original v0.3 implementation plan.
> - `docs/superpowers/plans/2026-04-27-v0.3.2-vod-parity.md` — v0.3.2 parity pass (peer page, dedicated components, consent defaults).

## Goal

Add support for downloading non-live YouTube performances — Tiny Desk Concerts, KEXP sessions, NPR Music Field Recordings, festival highlights, single-artist VODs — into concertpvr's library through three workflows: one-shot URL paste, channel subscription with auto-pull, and playlist ingest. Capture rich metadata (description, tags, detected setlists) at probe time. Allow auto-publish for trusted channels. Keep live recording behavior bit-identical for users who don't opt in.

## Architecture summary

Approach: hybrid — split downloaders, share probe; new VOD queue independent of the live pool.

**New modules** (single-responsibility, isolated):
- `src/concertpvr/vod_downloader.py` — finite-file yt-dlp invocation with `--continue` resume. Different from `recorder.py`: single output file (not fragment dir), determinate progress (`bytes_downloaded / bytes_total`), success on exit-0.
- `src/concertpvr/vod_queue.py` — separate concurrency-capped queue. Persistent FIFO via `Recording.status='vod_queued'` rows. Rehydrated at startup.
- `src/concertpvr/setlist_detector.py` — pure functions to extract setlists from description text and comment lists. Reuses existing setlist-paste regex.
- `src/concertpvr/artist_extractor.py` — pure function `extract_artist(title, regex) -> str | None`. Named `(?P<artist>...)` group required if regex has any groups.
- `src/concertpvr/playlist_ingest.py` — `expand_playlist(url) -> list[StreamInfo]` via yt-dlp flat extract.

**Existing modules with surgical edits:**
- `channel_poller.py` — add VOD-uploads check branch alongside the existing live-broadcasts branch, gated on `Watcher.watch_vod_uploads`.
- `models.py` — `Watcher`, `Stream`, `Recording`, `Segment`, `Settings` gain new columns (additive only).
- `api/streams.py` — `POST /api/streams` already creates `kind="video"` rows for non-live URLs; wire into the new VOD queue.
- `main.py` lifespan — add `vod_queue.start_workers()` and `mark_vod_downloads_interrupted_on_startup()` after the existing v0.2 orphan-recovery + scheduler setup, preserving strict ordering.
- `metadata.py` — `SegmentMeta` gains optional `genres: list[str]` and `plot: str | None`. Existing call sites use defaults → byte-identical NFO output.
- `publisher.py` — token resolution extends with `{channel}` and updated `{year}` / `{date}` / `{festival}` semantics (see Token Semantics below).

**Untouched on the happy path:** `recorder.py`, `pool.py`, `buffer.py`, `splitter`, `scheduler`, `chapters` (segmentation parser is mode-agnostic), live API endpoints, live tests.

**Blast-radius commitments:**
- Migration is additive only (new columns with `NOT NULL DEFAULT` or `NULL`). No drops, renames, or type changes.
- Live pool and VOD queue never share state — bulk VOD downloads cannot block live captures.
- Watchers with `watch_vod_uploads=false` (the default for existing rows) take the existing-behavior code path. Existing live tests stay green.
- All existing folder_pattern usage is preserved — `{year}` / `{date}` / `{festival}` continue to work for live recordings exactly as before, with new fallback logic only when the new VOD-only fields are populated.

## Decisions log

Tracking the brainstormed decisions so future readers know which trade-offs were considered.

| # | Decision | Rationale |
|---|---|---|
| 1 | Workflows A+B+C required; D folded into a per-watcher backlog browser. | Forward-only auto-pull keeps disk surprises away. Backlog browser turns "download old stuff" into a deliberate user action. |
| 2 | Unified watcher entity with independent `watch_live` + `watch_vod_uploads` toggles. | One row per channel; rare both-modes case is supported without duplicating channel rows. Note: if title-filter divergence becomes painful in practice, fallback option is splitting into `live_watchers` + `vod_watchers` tables. |
| 3 | Forward-only by default for new subscriptions; explicit backlog browser for curated picks. | No auto-backfill avoids accidental TB-scale pulls. |
| 4 | Per-watcher segmentation mode dropdown: `chapters` / `whole-video` / `manual`. Default `chapters`. URL-paste defaults to `chapters` with pre-publish review. | Tiny Desk → `whole-video`; festival highlights → `chapters`; messy uploads → `manual`. |
| 5 | Separate VOD queue with own concurrency cap (`max_concurrent_vod_downloads`, default 2). Live pool stays at `max_concurrent_recordings` (default 4). | Lives are time-sensitive; VODs aren't. Bulk VOD pulls must never starve a live show. |
| 6 | Unified Sources page (renamed from Streams) with kind badges Live/Video and a kind filter chip. | One mental model; "everything I've ingested" filters cleanly. |
| 7 | Per-watcher `auto_publish` toggle, off by default. Falls back to manual review when artist regex doesn't match cleanly. | Trust is per-channel. Off by default is safe. Failure-soft to manual review prevents wrong metadata silently landing in Emby. |
| 8 | Per-watcher artist regex with named `(?P<artist>...)` group. No match → manual review. | Channel-specific tuning beats hardcoded patterns. Docs ship with copy-paste recipes for ~5 known channels. |
| 9 | Genre filter added to Sources page and Library page. Backlog tab keeps title + duration filters only. | Genre data isn't returned by yt-dlp's flat-extract; full probe per video would cost ~60-100s per backlog open. |
| 10 | Source-file deletion gated on all segments being `published`; per-watcher and global auto-delete settings; per-recording manual delete button always available. | Reclaims disk after a festival's per-artist segments land in Emby. One-way operation; UI warns before triggering. |

## Data model changes — migration `0008_vod_support`

All additive, all nullable or defaulted, zero drops/renames.

### `watchers` — 9 new columns

| Column | Type | Default | Purpose |
|---|---|---|---|
| `watch_live` | `BOOLEAN NOT NULL` | `TRUE` | Existing watchers default to current behavior. |
| `watch_vod_uploads` | `BOOLEAN NOT NULL` | `FALSE` | Off by default; existing rows unaffected. |
| `vod_segmentation_mode` | `VARCHAR NOT NULL` | `'chapters'` | One of `chapters` / `whole-video` / `manual`. Pydantic Literal at API boundary. |
| `vod_title_filter` | `VARCHAR NULL` | `NULL` | Separate from existing `title_filter` (live). NULL = no filter. |
| `vod_artist_regex` | `VARCHAR NULL` | `NULL` | Pydantic-validated: must `re.compile`; if any groups, must include named `artist` group. |
| `auto_publish` | `BOOLEAN NOT NULL` | `FALSE` | VOD-only — live recordings ignore. |
| `extract_setlist_from_comments` | `BOOLEAN NOT NULL` | `FALSE` | Opt-in (slow probe). |
| `default_genres` | `VARCHAR NULL` | `NULL` | Comma-separated. Inherited by segments lacking their own. |
| `auto_delete_source_after_publish` | `BOOLEAN NULL` | `NULL` | NULL = inherit `Settings.auto_delete_source_after_publish`. |

### `streams` — 6 new columns

| Column | Type | Default | Purpose |
|---|---|---|---|
| `original_upload_date` | `DATE NULL` | `NULL` | yt-dlp `release_date` if present, else `upload_date`. NULL for lives. |
| `description` | `TEXT NULL` | `NULL` | Truncated at 2 MB if needed (logged WARNING). NULL for lives. |
| `youtube_tags` | `JSON NULL` | `NULL` | Raw tags list from yt-dlp; surfaced in UI as click-to-add chips. |
| `detected_setlist_text` | `TEXT NULL` | `NULL` | Raw text excerpt where setlist was detected. User can edit and re-apply. |
| `detected_setlist_source` | `VARCHAR NULL` | `NULL` | One of `chapters` / `description` / `comments` / NULL. Provenance. |
| `watcher_id` | `INTEGER NULL FK → watchers.id ON DELETE SET NULL` | `NULL` | Back-pointer for watcher-originated streams. Enables Sources filter "From watcher". |

### `segments` — 1 new column

| Column | Type | Default | Purpose |
|---|---|---|---|
| `genres` | `VARCHAR NULL` | `NULL` | Comma-separated per-segment override. NULL = inherit watcher default. |

### `recordings` — 2 new columns

| Column | Type | Default | Purpose |
|---|---|---|---|
| `auto_publish_after_download` | `BOOLEAN NOT NULL` | `FALSE` | Set by channel poller when watcher.auto_publish=true; checked at download-complete. |
| `source_deleted` | `BOOLEAN NOT NULL` | `FALSE` | Once true, recording is published-only — can't re-segment. |

### `settings` — 2 new columns

| Column | Type | Default | Purpose |
|---|---|---|---|
| `max_concurrent_vod_downloads` | `INTEGER NOT NULL` | `2` | VOD queue cap. ge=1, le=8 at API boundary. |
| `auto_delete_source_after_publish` | `BOOLEAN NOT NULL` | `FALSE` | Global default for source-deletion behavior. |

**Total: 20 new columns across 5 tables. Migration upgrade adds them; downgrade drops them. No data migration logic required (defaults populate existing rows).**

### Reused without schema change

- `Stream(kind="video")` — already valid; flow gets fleshed out properly.
- `Recording` — gains two new status string values: `vod_queued`, `vod_downloading`, `vod_failed`. The `status` column has no DB enum constraint; changes are documented + Pydantic Literal at API boundary.
- `Segment` — segmentation pipeline is mode-agnostic; reused as-is.

## API surface

### Existing endpoints with extended behavior

**`POST /api/streams`** — already accepts non-live URLs and creates `kind="video"`. Now also: routes channel URLs (200 with `{type:"channel", probed_meta}` for the smart-paste modal to handle) and playlist URLs (200 with `{type:"playlist", count, items}`). Returns `201` with the new Stream + Recording IDs for single-video VOD URLs.

**`PATCH /api/watchers/{id}`** — accepts the 9 new fields. Pydantic validators on `vod_artist_regex` (must compile; if has groups, must include `artist`) and `vod_title_filter` (must compile).

**`GET /api/recordings?status=vod_queued`** — uses v0.2's status filter; status enum extended.

### New endpoints

**`GET /api/watchers/{id}/backlog?limit=50&offset=0&sort=newest`** — paginated channel-videos listing via yt-dlp flat-extract. Each item carries `status: "downloaded" | "queued" | "not_downloaded"` (left-join against existing Streams by `youtube_id`). Sort options: `newest` (default), `most_viewed`, `longest`, `oldest`.

**`POST /api/watchers/{id}/backlog/download`** body `{video_ids: [...]}` — full-probes each, creates Stream + Recording rows, enqueues. Returns 201 with new IDs.

**`POST /api/playlists/ingest`** body `{url}` — probe-only; returns playlist metadata + items list with `is_already_known` flag per video. Capped at 500 items via yt-dlp `playlistend=500`; UI shows "Showing first 500 of N" if truncated.

**`POST /api/playlists/ingest/confirm`** body `{video_ids: [...], default_genres?, segmentation_mode?}` — creates Stream + Recording rows for selected, applies optional defaults to each. Returns 201 with new IDs.

**`POST /api/recordings/{id}/retry`** — for a `vod_failed` recording, requeues. Returns 200.

**`DELETE /api/recordings/{id}/source`** — verifies all segments are `published`, removes buffer dir / staging file, sets `source_deleted=true`. Returns 204. 409 if any segment not published.

### WebSocket

Existing `/ws/recordings/{id}/progress` topic publishes VOD progress events (`bytes_downloaded`, `bytes_total`, `pct`, `eta_s`). The frontend's existing `LiveProgressBar` component reused with a new `mode="determinate"` prop.

## Token semantics for `folder_pattern`

| Token | Live recording | VOD with metadata | Notes |
|---|---|---|---|
| `{artist}` | from segment | from segment | unchanged; per-segment value |
| `{title}` | from segment | from segment | unchanged |
| `{year}` | `recording.started_at.year` | `stream.original_upload_date.year` if set, else `started_at.year` | new fallback |
| `{date}` | `recording.started_at.date()` | `stream.original_upload_date` if set, else `started_at.date()` | new fallback |
| `{festival}` | em-dash split of stream title | `stream.channel_name` for VODs (kind=video) | per-kind dispatch |
| `{venue}` | em-dash split of stream title | NULL by default for VODs (no convention) | unchanged for live |
| `{channel}` | `stream.channel_name` | `stream.channel_name` | new token; explicit channel without festival's split logic |

Folder-pattern Pydantic validator (added in v0.2 T4) extends to include `channel`. Existing patterns unaffected.

## Setlist detection

**Sources, in priority order:**

1. **yt-dlp chapters** — already used for segmentation in `chapters` mode. Highest signal.
2. **Description text** — always parsed (free at probe time). Patterns: `0:00 - Song`, `[03:21] Song`, `01. Song / 02. Song`, `Artist · hh:mm-hh:mm`. Reuses existing setlist-paste regex from `chapters.py`.
3. **Top pinned comment + first ~50 comments** — opt-in per-watcher (`extract_setlist_from_comments`). Adds `getcomments=True` to yt-dlp opts. ~3-5s slower probe. Same pattern parser as description.
4. **External APIs (setlist.fm, etc.)** — out of scope. Documented as future enhancement.

**Capture-not-apply:** detected setlist lands on `streams.detected_setlist_text` + `streams.detected_setlist_source`. UI surfaces as a card on the post-download review screen with Apply/Edit/Dismiss. Auto-publish does NOT auto-apply detected setlists — only the existing path (regex-extracted artist + clean segmentation) triggers auto-publish.

**For NFO:** if a single-artist segment has a detected setlist, the song list is appended to NFO `<plot>` under a `Setlist:` header. Multi-act festival cases use chapters for segmentation; per-segment plots stay clean.

**Edge cases:**
- Multiple candidate sections in description → pick the longest contiguous block of timestamped lines; ties → earliest position.
- Comment fetch timeout (>10s) → fall back to no setlist; probe still succeeds.
- Malformed timestamps in entries → drop those lines, keep valid; if zero valid, treat as no setlist.

## Auto-publish logic

Auto-publish fires only when ALL of:
1. `Recording.auto_publish_after_download = true` (set at queue time when watcher.auto_publish=true AND watcher created the recording via the channel-poller path — not the backlog-browser path, where the user is curating).
2. `extract_artist(stream.title, watcher.vod_artist_regex)` returned a non-null `artist` group.
3. Segmentation produced ≥1 segment with non-null artist on each.
4. No probe/download/segment errors.

Otherwise: `Recording.status = "complete"`, segments stay `draft`, user reviews via the post-download review screen.

**Channel poller flow:**

```
for watcher in active_watchers:
    if watcher.watch_live:
        check_for_new_lives(watcher)  # existing path
    if watcher.watch_vod_uploads:
        check_for_new_vod_uploads(watcher)  # new path

# inside check_for_new_vod_uploads:
recent = flat_extract_uploads(watcher.channel_url, limit=20)
for entry in recent:
    if entry.is_live: continue  # covered by live path
    if Stream.exists(youtube_id=entry.id): continue  # dedupe
    if entry.upload_date < watcher.created_at: continue  # forward-only
    if watcher.vod_title_filter and not re.search(watcher.vod_title_filter, entry.title): continue
    info = full_probe(entry.url, opts={'getcomments': watcher.extract_setlist_from_comments})
    setlist = setlist_detector.detect(info, watcher)
    stream = Stream.create(kind='video', watcher_id=watcher.id, ...info, ...setlist)
    artist = artist_extractor.extract(info.title, watcher.vod_artist_regex)
    auto_pub = watcher.auto_publish and artist is not None
    Recording.create(stream_id=stream.id, status='vod_queued',
                     auto_publish_after_download=auto_pub)
    vod_queue.enqueue(recording.id)
```

## Source-file lifecycle

Recording's source file (live: buffer fragment dir, VOD: single staging file) is preserved by default. Three deletion paths:

1. **Auto-delete after auto-publish** — watcher-driven workflow with `watcher.auto_delete_source_after_publish=true` (or NULL inheriting `settings.auto_delete_source_after_publish=true`). Fires when all segments reach `published`.
2. **Manual per-recording deletion** — `DELETE /api/recordings/{id}/source` endpoint. Verifies all segments are `published` (409 otherwise), then removes the source file/dir, sets `source_deleted=true`. UI shows confirm dialog: "This permanently removes the source. You won't be able to create new segments from this recording or re-cut existing ones. Continue?"
3. **Existing `auto_prune_when_full` retention pruner** (from v0.1.1) — unchanged; still prunes oldest buffer fragments globally when disk pressure hits.

`source_deleted=true` is one-way. UI never offers "undelete" (file is gone). Re-downloading from YouTube is the recovery path.

## UI changes

### Renames

- "Streams" tab → "Sources".

### Sources page

- "Add URL" button (top-right, terra accent) opens the smart-paste modal.
- Filter chip rows: kind (`All / Live / Video`), watcher (`All / <each>`), genre (multi-select; AND-logic), title text search.
- Each row: thumbnail, title, channel, kind badge (terra=Live, sage=Video), genre pills (per-segment), status (Live: `Buffering / Idle`; Video: `Queued / Downloading {pct}% / Complete / Failed`).

### Smart-paste modal

Single URL input → backend probes → modal switches to one of three views:
- **Single video VOD** — preview card, "Queue download" / "Cancel" buttons. Setlist-detected indicator if present.
- **Channel** — preview card, three checkboxes (Live broadcasts / New VOD uploads / Auto-publish), "Subscribe" button. Helper text: "Forward-only. Click 'Browse backlog' on the watcher to pick old videos."
- **Playlist** — playlist preview header, title-filter input, scrollable list of items with checkboxes (already-in-library greyed out), optional "Apply settings to all" panel (segmentation mode + genres), "Queue N downloads" button.

### Watcher detail page

Two tabs added beyond existing fields:
- **Settings tab** — two-column layout. Left: "Watching for" (live/VOD checkboxes), VOD filters (title regex, artist regex with named-group helper), segmentation dropdown. Right: library defaults (genres autocomplete from ~30 built-in), automation (auto-publish, extract-from-comments, auto-delete-source toggles), activity stats.
- **Backlog tab** — multi-select grid of channel videos. Each card: thumbnail with state badge corner (Downloaded / Queued), title, upload age, view count, 🎵 if setlist detected, checkbox + "Download" button per row. Sort chips: Newest (default), Most viewed, Longest, Oldest. Title filter input. Bulk-download button at top when ≥1 selected. "Load 50 more" pagination.

### Recordings page

- Status filter chips include `vod_queued`, `vod_downloading`, `vod_failed`.
- VOD recordings show determinate progress (`pct` + `eta_s`) using existing `LiveProgressBar` with `mode="determinate"` prop.

### Post-download review screen (new)

Route: `/recordings/{id}/review`. Shown when a VOD recording transitions to `complete` AND has no segments yet AND auto-publish didn't fire. Layout:
- Header: thumbnail, title, channel, duration, upload date, description (collapsed with "Show more").
- Detected setlist card (if present): timestamped entries, Apply / Edit / Dismiss buttons.
- Segments list pre-populated by mode. Per-row: artist input, title input, time range, genres input with autocomplete, YouTube-tag suggestion chips below.
- "+ Split into multiple segments" → drops user into existing Timeline editor.
- Footer: Save as draft / Open in Timeline editor / Publish to Emby (terra primary).

### Timeline editor extensions

- Setlist paste modal pre-fills text input with `stream.detected_setlist_text` if present.
- Segment sidebar gains genres autocomplete field below the existing artist input.
- YouTube-tag chips shown as click-to-add suggestions below the genres field.

### Library page

- Genre filter chip row (multi-select, AND-logic).
- Year filter chip row (`All / 2025 / 2024 / 2023 / Earlier`).
- Per-poster genre pills under the artist/title.

### Dashboard

- Stat strip splits "Recording now" into two cards:
  - "Live now" `2/4` (terra-accent left border).
  - "VODs downloading" `1/2` (sage-accent left border).
- Helper text below stat strip: "Pools are separate so a 30-video Tiny Desk backfill click never starves a live show."

### Settings page

- New row "Max concurrent VOD downloads" (default 2, ge=1, le=8).
- New row "Auto-delete source after publish" (off by default; explanation: "When all segments on a recording are published, the source file is removed. You won't be able to re-cut.").

## Lifespan / startup ordering

Extends v0.2's strict sequence:

1. `Base.metadata.create_all(app.state.db.engine)`
2. `mark_interrupted_on_startup(app.state.db)` (existing — recordings stuck in `recording`)
3. `mark_vod_downloads_interrupted_on_startup(app.state.db)` *(new — `vod_downloading` rows from a crash transition back to `vod_queued`)*
4. Eager `session_secret` block (existing v0.2 work)
5. `register_app(...)` — wires pool, **vod_queue**, scheduler, broadcaster
6. `scheduler.start()` + `vod_queue.start_workers()`
7. `vod_queue.rehydrate_from_db()` (existing schedule rehydration runs in parallel)

Same blast-radius rule as v0.2's lifespan: orphan scans MUST run before `register_app` so scheduled jobs can't fire and create rows the scan would nuke.

## Error handling and edge cases

**Probe failures** (existing pattern, extended to channel/playlist URLs):
- Private/removed/age-restricted/region-locked → `ProbeError` → API 400 with yt-dlp message.
- Channel exists but zero uploads → `POST /api/watchers` succeeds; backlog tab empty.
- Empty/private playlist → `POST /api/playlists/ingest` → 400.

**Download failures:**
- yt-dlp non-zero exit → `Recording.status="vod_failed"`, error stored on `Recording.error` (stderr tail capped at 500 chars). UI shows retry button → `POST /api/recordings/{id}/retry`.
- Network drop mid-download → yt-dlp `--continue` resumes from partial file on retry.
- Disk full → existing `auto_prune_when_full` runs first; if still no space → `vod_failed`.
- Format unavailable → `vod_failed` with explicit error.

**Setlist detector edge cases** — see Setlist detection section.

**Artist extraction edge cases:**
- Regex matches but `artist` group is empty → treated as no match (manual review).
- Regex fails to compile → caught at PATCH validator (422). Won't reach runtime.
- Unicode (em-dashes, accents) preserved.

**Playlist edge cases:**
- 1000-item playlist → preview capped at 500 items; UI shows "Showing first 500 of 1000".
- Mixed-availability playlist (some private/deleted) → unavailable items rendered with `available=false`; checkboxes disabled.
- Same video in multiple playlists → dedupe by `youtube_id` before queueing.

**Source-delete guards:**
- 409 Conflict if any segment is not `published` at the time of deletion.
- Race protection: re-check segment statuses inside a DB transaction before unlinking files.
- File operation errors during deletion (locked, permission denied) → `Recording.source_deleted` stays false; error logged + UI surfaces error toast.

**Migration safety:**
- Test plan: load v0.2 DB fixture → run migration `0008` → assert all existing rows come up with safe defaults (watcher rows: `watch_live=true`, all VOD-mode toggles off; recording/stream/segment/settings rows: defaults applied). All v0.2 tests stay green when run against the migrated schema.

## Testing strategy

Estimated **~25-30 new tests**; full suite ~220.

### Unit tests
- `setlist_detector.detect_in_description` against fixture strings (Tiny Desk, KEXP, Coachella samples — both real-world and adversarial).
- `setlist_detector.detect_in_comments` against fixture comment lists.
- `artist_extractor.extract_artist` with regex patterns for ~5 known channels.
- `playlist_ingest.expand_playlist` with mocked yt-dlp flat-extract response.
- `vod_queue` — FIFO ordering, capacity enforcement, rehydration round-trip.

### API tests
- `POST /api/streams` with VOD URL → expect `Stream(kind=video)` + `Recording(status=vod_queued)`.
- `POST /api/streams` with channel URL → expect routing payload (`type=channel`).
- `POST /api/streams` with playlist URL → expect routing payload (`type=playlist`).
- `PATCH /api/watchers` accepts all 9 new fields; validates regexes (compile + named-group requirement).
- `GET /api/watchers/{id}/backlog` returns marked status; sort order respected.
- `POST /api/watchers/{id}/backlog/download` queues correctly.
- `POST /api/playlists/ingest` + confirm flow (selected subset, defaults applied).
- `POST /api/recordings/{id}/retry` requeues failed.
- `DELETE /api/recordings/{id}/source` — 204 on clean state, 409 on any non-published segment, file unlink verified.
- `GET /api/recordings?status=vod_queued` returns expected rows (uses v0.2 status filter).

### Channel-poller tests
- Watcher with live-only → existing live behavior, no VOD calls.
- Watcher with both modes → calls both branches.
- Watcher with `auto_publish=true` + matching artist regex → sets `auto_publish_after_download=true` on created Recording.
- Watcher with `auto_publish=true` + no regex match → flag stays false, manual review path.
- Forward-only filter excludes uploads older than `watcher.created_at`.

### Lifespan/migration tests
- VOD queue rehydration: seed `vod_downloading` row, restart TestClient → assert `vod_queued`.
- Migration 0008 against v0.2 fixture DB → assert defaults populate; existing tests pass.

### Auto-delete tests
- All segments published + auto_delete=true → source file removed, `source_deleted=true`.
- Some segments published + auto_delete=true → source preserved.
- Manual delete with non-published segments → 409.
- Manual delete with all published → 204, file removed.

### Frontend
- Typecheck + build clean (existing pattern; no new test framework).
- Manual smoke entries in `docs/release-checklist.md` (one per workflow + one for source deletion).

## Open questions / explicit non-goals

**Out of scope for this feature:**
- External setlist sources (setlist.fm, MusicBrainz). Documented as future enhancement.
- VOD scheduling (scheduling a known-now URL doesn't make sense; nothing in `Schedule` table extends to VODs).
- Auto-publish for one-shot pastes or playlist ingest. Trust signal is per-channel only.
- Genre filter on the Backlog tab. Data not available cheaply; could be added later if probe-on-demand becomes acceptable UX.
- Multi-language descriptions / chapters. yt-dlp returns the default; no localization handling.
- WebSocket auth on `/ws/recordings/{id}/progress`. Existing v0.2 limitation; out of scope.
- Frontend automated test suite. Existing v0.2 limitation; out of scope.

**Future enhancements:**
- "Bulk-approve all from this channel" button (Q7's option C) — layer on later if manual review of many auto-publish-failed rows becomes painful.
- Setlist.fm integration as a 4th setlist source.
- Per-segment NFO `<actor>` for festival multi-act sets where comments have detailed song-level setlists.
- D split-watcher fallback: if shared title-filter on unified watcher proves limiting, splitting into separate `vod_watchers` table is a clean second pass.

## Migration / version

Lands as **v0.3.0**. Same release-process as v0.2 (phase plan in `docs/superpowers/plans/`, subagent-driven implementation per wave, final tag).
