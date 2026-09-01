# Configuration Reference

Complete configuration guide for Digestarr.

> **Quick Start:** only 2 fields are required. See [Minimal Configuration](#minimal-configuration).

---

## Table of Contents

- [Minimal Configuration](#minimal-configuration)
- [Configuration Fields](#configuration-fields)
- [Configuration Methods](#configuration-methods)
- [Environment Variable Behavior](#environment-variable-behavior)
- [Docker Secrets](#docker-secrets)
- [Examples](#examples)
- [Discord Notification Notes](#discord-notification-notes)
- [Operational Guide](#operational-guide)
- [Troubleshooting](#troubleshooting)
- [Source of Truth](#source-of-truth)
- [See Also](#see-also)

---

## Minimal Configuration

Only these fields are required:

1. `tautulli_url`
2. `tautulli_api_key`

All other fields are optional and fall back to defaults.

```yaml
# deployment env file (example: docker-compose.yml)
environment:
  - TAUTULLI_URL=http://tautulli:8181
  - TAUTULLI_API_KEY=/run/secrets/tautulli_api_key
```

**Notes:**

- Timezone defaults to UTC. Set `TZ` for local timezone (for example `TZ=America/New_York`).
- Iterative fetch logs (`iteration 1, 2, 3...`) are expected because Tautulli has no date filter on recently-added data.
- Safety guardrails prevent runaway fetch loops on unusual API behavior.

### Retry Logic

Both API clients use exponential backoff retries.

- **Tautulli:** 3 retries (`1s`, `2s`, `4s`), `10s` timeout, retries on network/timeout/HTTP 5xx.
- **Discord:** 3 retries (`1s`, `2s`, `4s`), `15s` timeout, respects HTTP 429 `retry_after`, no retry on HTTP 400.

---

## Configuration Fields

All fields are defined in `src/config.py`.

| Field                  | Type    | Required         | Default                 | Validation                            | Description                                                        |
| ---------------------- | ------- | ---------------- | ----------------------- | ------------------------------------- | ------------------------------------------------------------------ |
| `media_source`         | string  | No               | `"tautulli"`            | tautulli, tracearr                    | Where recently added media is read from                            |
| `tracearr_url`         | string  | ⚠️ Conditional\*\*\*  | -                       | -                                     | Tracearr URL (required when `media_source` is `tracearr`)          |
| `tracearr_api_key`     | string  | ⚠️ Conditional\*\*\*  | -                       | -                                     | Tracearr public API token                                          |
| **`tautulli_url`**     | string  | ⚠️ Conditional\*\*\*  | -                       | -                                     | Full URL to Tautulli instance (for example `http://tautulli:8181`) |
| **`tautulli_api_key`** | string  | ⚠️ Conditional\*\*\*  | -                       | -                                     | Tautulli API key                                                   |
| `days_back`            | integer | No               | `7`                     | ≥ 1                                   | Days to look back for new media                                    |
| `cron_schedule`        | string  | ⚠️ Conditional\* | `"0 16 * * SUN"`        | Valid CRON                            | Schedule for automated runs                                        |
| `discord_webhook_url`  | string  | No               | `None`                  | -                                     | Discord webhook URL                                                |
| `media_server_url`     | string  | No               | `"https://app.plex.tv"` | -                                     | Media server URL used for generated links (Plex, Jellyfin, Emby)   |
| `media_server_id`      | string  | No               | Auto-detected\*\*\*\*        | -                                     | Server identifier; required for Plex links, optional otherwise     |
| `run_once`             | boolean | No               | `false`                 | -                                     | `true` runs once, `false` runs scheduled                           |
| `log_level`            | string  | No               | `"INFO"`                | DEBUG, INFO, WARNING, ERROR, CRITICAL | Logging verbosity                                                  |
| `initial_batch_size`   | integer | No               | Adaptive\*\*            | 1-10000                               | Tautulli API batch size override                                   |
| `excluded_media_types` | list    | No               | `[]`                    | movie, show, season, episode, album, track | Media types omitted from the summary                          |
| `enable_healthcheck`   | boolean | No               | `false`                 | -                                     | Serve `GET /health` (scheduled mode only)                          |
| `health_host`          | string  | No               | `"127.0.0.1"`           | non-empty                             | Interface the health endpoint binds to                             |
| `health_port`          | integer | No               | `8080`                  | 1-65535                               | Port for the health endpoint                                       |

\* `cron_schedule` is required when `run_once` is `false`.

\*\* Adaptive default: `100` (≤7 days), `200` (≤30 days), `500` (>30 days).

\*\*\* Only the selected `media_source`'s credentials are required.

\*\*\*\* Auto-detected via Tautulli only. Tracearr cannot report it, so set it explicitly there. A Tautulli install needs `tautulli_url` and `tautulli_api_key`; a Tracearr one needs `tracearr_url` and `tracearr_api_key`.

### Excluding media types

`excluded_media_types` drops entries before they reach the logs, the item count and the
notification, so every total stays consistent with what is shown. Unknown values are
rejected at startup rather than silently ignored.

In `config.yml` it is a list:

```yaml
excluded_media_types:
  - track
  - album
```

Because environment variable interpolation always yields a string, the same setting is
also accepted comma-separated, which is the usual form for container deployments:

```bash
EXCLUDED_MEDIA_TYPES=track,album
```


### Choosing a media source

`media_source` selects where recently added media is read from.

**Tracearr is the recommended source** and where new features go: it fronts Plex,
Jellyfin and Emby, and exposes data Tautulli does not. **Tautulli is in maintenance** —
it keeps working and keeps getting fixes, but new capabilities are not backported to it.
It stays worth choosing when you want no extra infrastructure, or you are on Plex and
want the server id detected for you.

`media_source` **still defaults to `tautulli`**, so no existing install changes
behaviour by upgrading.

```yaml
media_source: tracearr
tracearr_url: http://tracearr:3000
tracearr_api_key: ${TRACEARR_API_KEY}   # a trr_pub_... token from Tracearr's UI
```

Only the selected source's credentials are required, so a Tracearr install does not
need Tautulli configured at all.

Two differences are worth knowing before switching:

- **Links need `media_server_id` set by hand.** Tracearr exposes no server identifier
  on its public API, so it cannot be auto-detected. The app warns once at startup and
  omits the links unless you set the field yourself. Only Plex requires it — Jellyfin
  and Emby links are built without one.
- **Grouping is reconstructed.** Tautulli relays Plex's *recently added* hub, which
  collapses a bulk import into a single show or season entry. Tracearr exposes every
  row, so the client regroups them: episodes of one show that arrived together become
  one entry, while an isolated weekly episode stays its own. On a real library this
  reproduces Tautulli's output — 213 raw rows became the same 17 entries, in the same
  order.
- **The two can disagree at the very edge of the window.** Plex's grouped entry is
  atomic: it carries the timestamp of its newest member and is either inside
  `days_back` or outside it as a whole. Tracearr's rows age out one by one, so a bulk
  import straddling the cutoff is seen only in part, and the remainder may regroup
  differently.

  A real example, with `days_back: 7` and three episodes added within a minute:

  ```
  episodes:  09:39:11   09:39:29   09:40:06
  cutoff:              ^ here
  ```

  Tautulli shows `Love, Death & Robots - Season 4` — its single entry is stamped
  09:40:06 and is still inside. Tracearr sees only the 09:40:06 episode, so it has no
  burst left to collapse and reports
  `Love, Death & Robots - S04E01 - Can't Stop` instead.

  Neither is wrong, and the difference disappears at the next run once the whole
  import has aged out. It only affects items within minutes of the `days_back`
  boundary, so a schedule that runs less often than `days_back` rarely meets it.

### Health endpoint

With `enable_healthcheck: true`, the app serves `GET /health` on a daemon thread and
answers `200` with `{"status": "ok", "last_run": "<iso-timestamp-or-null>"}`. Any other
path returns `404`. `last_run` is the last run that finished building a summary — it is
updated even if notification delivery failed, since it reports scheduler liveness
rather than delivery success.

**It only runs in scheduled mode.** In `run_once` mode the process exits immediately,
so no probe could reach it; the setting is ignored there.

**Network exposure.** `health_host` defaults to `127.0.0.1`, which is reachable only
from inside the container — all the Docker `HEALTHCHECK` needs. Nothing on your network
can reach it, and no port is published. Setting `health_host: 0.0.0.0` and publishing
the port exposes an **unauthenticated** endpoint; only do that if you want an external
monitor to probe it. The response contains no configuration, URLs or credentials.

The image's `HEALTHCHECK` runs `scripts/healthcheck.py`, which probes the HTTP endpoint
when it is enabled and otherwise falls back to a process check — so the default
(disabled) configuration still reports health correctly.

#### External monitoring (Uptime Kuma, Gatus, ...)

The default loopback bind is **not reachable** from an external monitor — not from the
host, and not from another container, even on the same Docker network. Publishing the
port alone does not help: the server is bound inside the container's own loopback.

To expose it, set both:

```yaml
environment:
  - ENABLE_HEALTHCHECK=true
  - HEALTH_HOST=0.0.0.0
```

then reach it one of two ways:

- **monitor outside Docker** — publish the port (`ports: ["8080:8080"]`) and point the
  monitor at `http://<docker-host>:8080/health`
- **monitor in a container on the same network (recommended)** — no port mapping
  needed; point it at `http://digestarr:8080/health`. If the monitor lives
  in a different Compose project, attach this container to the monitor's network the
  same way as for Tautulli:

  ```yaml
  networks:
    - <monitor_project>_default

  networks:
    <monitor_project>_default:
      external: true
  ```

  A container can join several networks, so this coexists with Tautulli's.

Configure it as a plain HTTP(s) monitor expecting `200`. The container's own
`HEALTHCHECK` keeps working in this mode: the probe script rewrites a `0.0.0.0` bind to
`127.0.0.1` for its own local request.

Remember the endpoint is **unauthenticated**. It discloses only a status string and the
last run timestamp, but anyone who can reach the address can read it, so prefer the
same-network option over publishing the port to your LAN.

---

## Configuration Methods

### 1) Environment Variables (recommended)

Set env vars in your deployment file and keep `${VAR}` references in `configs/config.yml`.

```yaml
# deployment env file (example: docker-compose.yml)
environment:
  - TAUTULLI_URL=http://tautulli:8181

# configs/config.yml
tautulli_url: ${TAUTULLI_URL}
```

### 2) Hardcoded Values

Useful for local testing.

```yaml
# configs/config.yml
tautulli_url: http://192.168.1.100:8181
tautulli_api_key: your_api_key
```

⚠️ Do not commit credentials.

### 3) Docker Secrets (recommended for production)

Set env vars to secret file paths. The app detects leading `/` and reads file contents.

```yaml
# deployment env file (example: docker-compose.yml)
environment:
  - TAUTULLI_API_KEY=/run/secrets/tautulli_api_key

# configs/config.yml
tautulli_api_key: ${TAUTULLI_API_KEY}
```

---

## Environment Variable Behavior

Default `configs/config.yml` already uses `${VAR}` placeholders for all fields.

- Set env vars for required fields (`TAUTULLI_URL`, `TAUTULLI_API_KEY`) always.
- Set env vars for optional fields only when overriding defaults.
- Leave optional env vars unset to use defaults.

| Env var state       | Required field (`TAUTULLI_URL`) | Optional field (`DAYS_BACK`) |
| ------------------- | ------------------------------- | ---------------------------- |
| Not set             | ❌ Startup error                | ✅ Uses default silently     |
| Empty string (`""`) | ❌ Startup error                | ⚠️ Warning, uses default     |
| Valid value         | ✅ Uses provided value          | ✅ Uses provided value       |

### Environment Variable Mapping

| Environment Variable  | Config Field          | Purpose                      |
| --------------------- | --------------------- | ---------------------------- |
| `TAUTULLI_URL`        | `tautulli_url`        | Tautulli URL (required)      |
| `TAUTULLI_API_KEY`    | `tautulli_api_key`    | Tautulli API key (required)  |
| `DAYS_BACK`           | `days_back`           | Days lookback override       |
| `CRON_SCHEDULE`       | `cron_schedule`       | Schedule override            |
| `DISCORD_WEBHOOK_URL` | `discord_webhook_url` | Enable Discord notifications |
| `MEDIA_SERVER_URL`    | `media_server_url`    | Media server URL override    |
| `MEDIA_SERVER_ID`     | `media_server_id`     | Media server id override     |
| `RUN_ONCE`            | `run_once`            | One-shot mode override       |
| `LOG_LEVEL`           | `log_level`           | Logging level override       |
| `INITIAL_BATCH_SIZE`  | `initial_batch_size`  | Batch size override          |
| `EXCLUDED_MEDIA_TYPES` | `excluded_media_types` | Comma-separated types to omit |
| `MEDIA_SOURCE`        | `media_source`        | tautulli (default) or tracearr |
| `TRACEARR_URL`        | `tracearr_url`        | Tracearr URL                 |
| `TRACEARR_API_KEY`    | `tracearr_api_key`    | Tracearr public API token    |
| `ENABLE_HEALTHCHECK`  | `enable_healthcheck`  | Enable the health endpoint   |
| `HEALTH_HOST`         | `health_host`         | Health endpoint bind address |
| `HEALTH_PORT`         | `health_port`         | Health endpoint port         |
| `TZ`                  | N/A                   | Container timezone           |
| `PUID`                | N/A                   | User ID (file permissions)   |
| `PGID`                | N/A                   | Group ID (file permissions)  |

---

## Docker Secrets

### Recommended Pattern (volume-mounted secrets)

```yaml
# deployment env file (example: docker-compose.yml)
services:
  app:
    volumes:
      - ./secrets:/run/secrets:ro
    environment:
      - TAUTULLI_API_KEY=/run/secrets/tautulli_api_key
      - DISCORD_WEBHOOK_URL=/run/secrets/discord_webhook
```

Create secret files:

```bash
mkdir -p secrets
echo "your_api_key" > secrets/tautulli_api_key
echo "https://discord.com/api/webhooks/..." > secrets/discord_webhook
chmod 600 secrets/*
```

### Alternatives

**Direct values (simpler, less secure):**

```yaml
environment:
  - TAUTULLI_URL=http://tautulli:8181
  - TAUTULLI_API_KEY=your_api_key_here
  - DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/123/abc...
```

**Docker Compose secrets:**

```yaml
services:
  app:
    secrets:
      - tautulli_api_key
    environment:
      - TAUTULLI_API_KEY=/run/secrets/tautulli_api_key

secrets:
  tautulli_api_key:
    file: ./secrets/tautulli_api_key
```

### How Values Are Processed

- Path value (starts with `/`) → app reads file content.
- Non-path value → app uses value directly.
- Required file-based fields fail fast when file is missing, unreadable, or empty.
- Optional file-based fields keep fallback behavior.

For broader hardening guidance, see [Security](README.md#security).

---

## Examples

### Example 1: Minimal production

```yaml
services:
  app:
    image: ghcr.io/thomas-lg/digestarr:latest
    volumes:
      - ./configs:/app/configs:ro
      - ./secrets:/run/secrets:ro
    environment:
      - TAUTULLI_URL=http://tautulli:8181
      - TAUTULLI_API_KEY=/run/secrets/tautulli_api_key
    restart: unless-stopped
```

### Example 2: Discord + one-shot

```yaml
services:
  app:
    image: ghcr.io/thomas-lg/digestarr:latest
    volumes:
      - ./configs:/app/configs:ro
      - ./secrets:/run/secrets:ro
    environment:
      - TAUTULLI_URL=http://tautulli:8181
      - TAUTULLI_API_KEY=/run/secrets/tautulli_api_key
      - DISCORD_WEBHOOK_URL=/run/secrets/discord_webhook
      - RUN_ONCE=true
      - DAYS_BACK=14
      - LOG_LEVEL=DEBUG
```

## Discord Notification Notes

- **Category summaries:** Movies, TV Shows, TV Seasons, TV Episodes, Music Albums, Music Tracks, and Other items are each grouped into their own rich embed.
- **Empty period:** if no items match the selected period, the app sends a single friendly "nothing new" embed.
- **Message style:** empty-period title/body text is selected from an internal randomized message set.
- **Large result sets:** content is trimmed/split into multiple messages to stay within Discord limits.
- **Delivery behavior:** uses the same retry/timeout behavior described in [Retry Logic](#retry-logic).

Discord embed limits:

- 6000 chars per embed (total)
- 1024 chars per field
- 25 fields per embed

---

## Operational Guide

### Configuration Auto-Creation

If missing, container creates `config.yml` on first run by copying `config.yml.default`, applying PUID/PGID ownership, and keeping `${VAR}` placeholders.

Container path contract:

- Config file: `/app/configs/config.yml`
- Logs directory: `/app/logs`

Reset defaults:

```bash
rm configs/config.yml && docker compose restart
```

### Exit Codes

| Code  | Meaning     | Typical cause                                      |
| ----- | ----------- | -------------------------------------------------- |
| `0`   | Success     | Completed successfully                             |
| `1`   | Error       | Config/API errors; Discord errors in one-shot mode |
| `130` | Interrupted | KeyboardInterrupt (`Ctrl+C`)                       |

### Logging

- Format: `%(asctime)s | %(levelname)-7s | %(name)s | %(message)s`
- Default level: `INFO` (shows first 10 items/type + total count)
- Use `LOG_LEVEL=DEBUG` to log all items and API detail
- Docker logs: `docker logs digestarr` or `docker logs -f digestarr`
- Rotating file logs at `/app/logs/app.log`:
  - 5 MB per file
  - 5 backups + current file (6 files max)

### Scheduler Behavior

In scheduled mode (`run_once: false`):

- Coalescing enabled (missed overlapping run not queued)
- Max instances = 1
- Missed runs are not replayed after restart
- Graceful shutdown handles SIGTERM/SIGINT

### Performance and Scaling

Approximate memory usage:

- Small libraries (<1000 items): ~50-100 MB
- Very large libraries (10000+ items): ~400-800 MB

Performance depends on library size, `days_back`, network latency, and Tautulli responsiveness.

Tuning examples:

```yaml
# Fewer API calls on large libraries / slow networks
environment:
  - INITIAL_BATCH_SIZE=1000
  - DAYS_BACK=7

# Fewer Discord trims
environment:
  - DAYS_BACK=3
```

### Backup and Restore

Backup:

```bash
tar czf backup-$(date +%Y%m%d).tar.gz configs/ secrets/
```

Restore:

```bash
docker compose down
tar xzf backup-YYYYMMDD.tar.gz
chmod 600 secrets/*
docker compose up -d
```

### Migration and Updates

```bash
cp configs/config.yml configs/config.yml.backup
docker compose pull && docker compose down && docker compose up -d
docker logs -f digestarr
```

- Use `:latest` for automatic updates.
- Use pinned tags (for example `:v1.0.0`) for stricter production control.

### Tautulli API Compatibility

- Endpoints: `get_recently_added`, `get_server_identity`
- Minimum: `v2.1.0`
- Recommended: `v2.5.0+`
- Tested: `v2.5.0` to `v2.13.0+`

API test:

```bash
curl "http://tautulli:8181/api/v2?apikey=YOUR_KEY&cmd=get_recently_added&count=10"
```

### Docker Networking

- Same Docker network: use container hostname (`http://tautulli:8181`)
- Tautulli on host:
  - Docker Desktop: `http://host.docker.internal:8181`
  - Linux host IP: `http://192.168.1.100:8181`
- External server: `http://tautulli.example.com:8181`

Useful checks:

```bash
docker network inspect bridge
docker exec digestarr ping tautulli
docker inspect tautulli | grep IPAddress
```

Linux `host.docker.internal` helper:

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

---

## Troubleshooting

### Configuration values ignored or missing

- Confirm env vars are set in deployment file.
- Confirm fields in `configs/config.yml` reference `${VAR}`.

### Unresolved environment variable error

- Required field references undefined/empty env var.
- Set non-empty `TAUTULLI_URL` and `TAUTULLI_API_KEY`.

### Discord notifications not sending

- Confirm `DISCORD_WEBHOOK_URL` is set.
- Test webhook with `curl`.
- If file-based, verify secret file exists and is readable.
- Check logs for env var warnings/errors.
- For empty-period and embed-limit behavior, see [Discord Notification Notes](#discord-notification-notes).

### CRON schedule not running

- Ensure `run_once` is `false`.
- Validate `cron_schedule` format.
- Verify timezone (`TZ`) and inspect container logs.

### Secret file not found/readable

- Verify mount: `./secrets:/run/secrets:ro`.
- Verify path: `TAUTULLI_API_KEY=/run/secrets/tautulli_api_key`.
- Verify permissions: `chmod 600 secrets/*`.
- Ensure required secret files are non-empty.

### Validation errors on startup

Check type and bounds:

- `days_back` integer ≥ 1
- `log_level` in `DEBUG|INFO|WARNING|ERROR|CRITICAL`
- `initial_batch_size` between 1 and 10000
- Valid `cron_schedule`

### Need more logs

```yaml
environment:
  - LOG_LEVEL=DEBUG
```

Then inspect:

```bash
docker logs -f digestarr
```

---

## Source of Truth

Configuration authority order:

1. `src/config.py` (schema, defaults, validation)
2. `configs/config.yml` (field wiring)
3. Deployment env values (for example `docker-compose.yml`)

When behavior seems unclear, check `src/config.py` first.

---

## See Also

- [Main README](README.md)
- [configs/config.yml](configs/config.yml)
- [docker-compose.yml](docker-compose.yml)
