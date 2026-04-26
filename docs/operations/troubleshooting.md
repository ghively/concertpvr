# Troubleshooting

Common failure modes and what to do. If you hit something not listed, the first stop is `docker compose logs concertpvr` (or `tail -f /volume1/concertpvr/logs/concertpvr.log` if you're inspecting from the host).

## yt-dlp probe / recording fails

**Symptom:** "Add stream" returns 400 with a yt-dlp error message; or a buffer toggle doesn't seem to record fragments.

- **Channel/video is private or member-only.** Set up a cookies file — see `docs/operations/cookies.md`.
- **YouTube changed their HTML structure.** yt-dlp gets updates frequently. Bump the pin in `pyproject.toml`, rebuild the image. Workaround: `docker compose exec concertpvr pip install -U yt-dlp` (resets on next image rebuild).
- **Channel handle URL not resolving.** Try the canonical `youtube.com/channel/UCxxxx` URL instead of `@handle`.

## Recording stops immediately or produces 0 fragments

- **yt-dlp exited non-zero.** Check `concertpvr.log` for the yt-dlp stderr. Common causes:
  - Stream isn't actually live (check on YouTube directly).
  - Format selector unsupported for this stream — try lowering `Default quality` in Settings to `best` or a specific format like `bv*[height<=1080]+ba/b`.
  - Network connectivity (check `docker compose exec concertpvr curl -I https://www.youtube.com`).

## ffmpeg "ffmpeg exited 1" on publish

- **Source recording is a directory of fragments, not a single file.** Buffer recordings produce `<dir>/*.ts`. Phase 4b only serves single-file recordings via `/api/recordings/{id}/media`. To publish from a buffer, finalize the recording first (`POST /api/recordings/{id}/finalize`), which captures yt-dlp chapters and marks complete; if you need a single playable file, the finalize endpoint doesn't currently mux fragments — concatenate manually:
  ```bash
  cd /volume1/concertpvr/buffer/<stream_id>
  printf "file '%s'\n" *.ts > concat.txt
  ffmpeg -f concat -safe 0 -i concat.txt -c copy ../../staging/manual_<stream_id>.mkv
  ```
  Then update the recording row's `path` via SQL.
- **Disk full.** Check `df -h` on the host.

## Emby library refresh doesn't fire

- **Emby URL/API key not configured.** Settings page → Emby Integration. Until both are set, the publish step skips the refresh call (it succeeds — the media file is still produced).
- **Emby URL unreachable from container.** Test with `docker compose exec concertpvr curl -f http://emby:8096/System/Info?api_key=YOUR_KEY`.
- **Wrong path in Emby.** The `Library/Media/Updated` API expects the path Emby itself sees. If your container bind-mounts `/volume1/media/concerts` into `/media/concerts`, but Emby's library uses `/volume1/media/concerts`, set `Movies library path (Emby's view)` in Settings to the Emby path. concertpvr uses our `Publish path` for the file write and the Emby path field is a separate hint (currently unused — known limitation in v0.1.0). Workaround: trigger Emby's "Scan Library" manually.

## Disk fills up

- **Buffer retention not set.** Each watch subscription has a `retention_days` (default 7). The retention pruner runs every 5 minutes — wait for it.
- **Auto-prune-when-full disabled.** Toggle on in Settings if you want concertpvr to free space automatically before refusing new recordings.

## Schedule didn't fire

- **App was restarted between schedule create and start time.** APScheduler jobs for schedules use the `memory` jobstore (closures over app state can't be serialized to the SQLAlchemy jobstore). The `ScheduleManager.rehydrate_from_db` runs on every startup to re-add jobs for `pending` schedules whose `starts_at > now`. If your schedule was within `now ± 30s` at restart, it may have missed the lead-time window. Check the schedule's `status` column in the DB.

## Channel watcher missing a live broadcast

- **Title filter regex doesn't match.** Test the regex: `python -c "import re; print(re.search('YOUR_FILTER', 'live title here', re.IGNORECASE))"`.
- **Already-known broadcast.** `last_live_id` column on the watcher row tracks the most recent triggered broadcast. If you delete it via SQL the watcher will re-record on next poll.
- **Polling job not registered.** Look for `channel_poller` in the log every 60 seconds.

## "Login screen never appears" or "I can't log in"

- **Password not set.** The login screen only appears after a password is set via Settings. Until then, the app is open on the LAN.
- **Cookie blocked by browser.** Check Site Settings → Cookies for your concertpvr origin.
- **Forgot the password.** No recovery flow exists in v0.1.0. SQL workaround:
  ```bash
  docker compose exec concertpvr sqlite3 /data/metadata.db \
    "UPDATE settings SET password_hash=NULL, session_secret=NULL WHERE id=1;"
  ```
  Then set a new password via Settings.

## Logs

- Container stdout: `docker compose logs concertpvr`
- Rotating log file: `/volume1/concertpvr/logs/concertpvr.log` (5 MiB × 5 backups)
- Database: `/volume1/concertpvr/metadata.db` (SQLite — open with any client)
