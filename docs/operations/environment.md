# Environment variables

All runtime configuration is read from environment variables prefixed `CPVR_`. Per-install settings (Emby URL, retention defaults, password) live in the `settings` SQLite table and are edited via the Settings page.

## Required

| Variable | Description |
|---|---|
| `CPVR_DATA_DIR` | Host directory for `metadata.db`, `buffer/`, `staging/`, `logs/`. Inside the Docker container this defaults to `/data`; outside Docker you must set it explicitly. |

## Optional

| Variable | Default | Description |
|---|---|---|
| `CPVR_PUBLISH_DIR` | `/media/concerts` | Where published segment folders land. Bind-mount your Emby movies library here. |
| `CPVR_STATIC_DIR` | unset | Path to the built React bundle. The Docker image sets this to `/app/static`. Unset in dev — the Vite dev server proxies. |
| `CPVR_HOST` | `0.0.0.0` | Uvicorn bind address. |
| `CPVR_PORT` | `8787` | Uvicorn bind port. |

## Computed paths (derived from `CPVR_DATA_DIR`)

- `db_path` = `<data_dir>/metadata.db`
- `buffer_dir` = `<data_dir>/buffer/`
- `staging_dir` = `<data_dir>/staging/`
- `logs_dir` = `<data_dir>/logs/`
