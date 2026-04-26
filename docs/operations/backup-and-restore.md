# Backup and restore

What's stateful in concertpvr and how to back it up.

## What's stateful

| Path | Contents | Recoverable from elsewhere? |
|---|---|---|
| `/volume1/concertpvr/metadata.db` | SQLite database — settings, streams, recordings, schedules, segments, setlists, channel watchers | **No.** Back this up. |
| `/volume1/concertpvr/buffer/` | Live-stream DVR fragments. One subdir per stream id. | **No** (after the live stream ends, fragments cannot be re-fetched). Back up if you have unfinished work. |
| `/volume1/concertpvr/staging/` | Finished scheduled recordings + intermediate split clips before publish. | **No.** Back up if you have unpublished segments. |
| `/volume1/concertpvr/logs/` | Rotating app log. | Yes (recreated on next start). Optional. |
| `/volume1/media/concerts/` | Published Emby movies. | **Yes** if you can re-publish from staging recordings. |

Only `metadata.db` is mandatory. The rest is up to your data-loss tolerance.

## Backup

The cleanest approach is a SQLite-aware dump (avoids partial-write corruption):

```bash
# On the Synology (or in the container)
docker compose exec concertpvr sqlite3 /data/metadata.db ".backup /data/metadata.db.bak"
```

Then copy the `.bak` file off the device. You can also stop the container and copy the `.db` file directly — it's a single file.

For the recordings directories, an `rsync` to a backup destination is fine (the buffer is the only directory that's actively written to during normal operation):

```bash
rsync -a --delete /volume1/concertpvr/staging/ /volume2/backups/concertpvr-staging/
rsync -a /volume1/concertpvr/metadata.db.bak /volume2/backups/
```

Schedule both via Synology Task Scheduler if you want this regular.

## Restore

1. Stop the container: `docker compose down`
2. Restore `metadata.db` to `/volume1/concertpvr/metadata.db` (overwrite or move into place).
3. Restore `staging/` and `buffer/` if you need them.
4. Start: `docker compose up -d`
5. App runs `alembic upgrade head` on startup — if your backup is from an older schema, migrations apply automatically.

## What survives a container rebuild

Everything in the bind-mounted volumes (`/volume1/concertpvr` and `/volume1/media/concerts`) survives `docker compose down && docker compose up -d --build`. The container itself is stateless.

## Disaster recovery

- **Lost the DB:** All recordings on disk become orphans. You'd have to re-create stream and schedule rows manually, then point them at the existing files. Painful but possible. Don't lose the DB.
- **Lost the buffer/staging dirs:** The DB still references them. Recordings in those dirs marked `complete` but with no file → API will return 404 on `/media`. You can either delete the orphan DB rows or null out their `path`.
- **Lost the published `concerts/` dir:** The DB has the segment rows with `emby_path`. You can re-publish from staging if those are still present.
