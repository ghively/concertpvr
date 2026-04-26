# Release smoke test checklist

Run through this before tagging a new version. Everything must pass.

## Boot

- [ ] `docker compose up -d --build` starts cleanly
- [ ] `curl http://localhost:8787/api/healthz` returns `{"status":"ok"}`
- [ ] `docker compose logs concertpvr` shows alembic running upgrades to head, scheduler started
- [ ] Browse http://localhost:8787 — the SPA loads, navigation works

## Auth

- [ ] Settings page → set a password
- [ ] Click Log out — redirected to /login
- [ ] Wrong password → 401, error message shown
- [ ] Correct password → redirected to dashboard
- [ ] All `/api/*` endpoints (except healthz + auth) require the cookie

## Stream buffer

- [ ] Streams → Add stream → paste a real YouTube live URL
- [ ] App probes via yt-dlp and shows title/channel
- [ ] Click Start buffer
- [ ] yt-dlp spawns; LiveProgressBar shows bytes/bitrate/duration updating in real time
- [ ] Click Stop buffer — recorder terminates cleanly
- [ ] After 5 minutes, retention pruner runs (check logs for "buffer_retention_prune")

## Scheduled recording

- [ ] Schedule → New schedule → URL + start time ~2 minutes from now + 1-minute window
- [ ] Schedule appears in calendar and Dashboard "Up Next" rail
- [ ] At fire time, schedule status flips pending → running → complete
- [ ] A new Recording row appears in the Recordings tab
- [ ] The .mkv file is in the staging directory

## Channel watcher

- [ ] Watchers → Add a channel — paste any active YouTube channel URL
- [ ] Channel name + avatar populate from probe
- [ ] Toggle one off and on
- [ ] Polling job fires every 60s (check `docker compose logs` for "channel_poller")
- [ ] If a watched channel goes live, a new buffer recording starts automatically

## Segment & publish

- [ ] Recordings → click a finished recording → Timeline editor opens
- [ ] Vidstack player loads the recording (range request seeking works)
- [ ] If the recording has yt-dlp chapters → segments auto-derived
- [ ] Drag empty timeline → new segment created
- [ ] Drag region edges → start/end persist (debounced PATCH)
- [ ] Click Publish → segment status flips publishing → published
- [ ] Library tab → poster card appears for the published segment
- [ ] Configured Emby movies path — verify the folder + movie.nfo + poster.jpg + fanart.jpg landed
- [ ] If Emby is configured — Emby reports the new movie within ~30s of publish

## UI polish

- [ ] Confirm dialogs replace browser native confirms for delete actions
- [ ] Setlist paste modal accepts unicode em-dashes and ASCII hyphens

## Logs

- [ ] `docker compose exec concertpvr ls /data/logs/` shows `concertpvr.log` rotating
- [ ] No errors at INFO level on a clean boot

## Tear down

- [ ] `docker compose down`
- [ ] Restart with `docker compose up -d` — schedules persist (rehydrated on startup), buffer fragments persist, segments + setlists persist
