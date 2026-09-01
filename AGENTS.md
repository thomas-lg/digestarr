# AGENTS.md — Digestarr

Conventions and gotchas for anyone — human or agent — working in this repository.
`.github/copilot-instructions.md` is the shorter companion; this file is the detailed
one. Keep them consistent when a convention changes.

## Language & Toolchain

- **Python 3.14** (set in `.python-version` and `pyproject.toml`). This is newer than most environments; don't downgrade syntax or use compatibility shims.
- Dependency manager: plain `pip` with compiled lockfiles (`requirements.lock`, `requirements-dev.lock`). Install from lockfiles.
- Runtime dependencies are declared **only** in `pyproject.toml` (`[project].dependencies`) — there is no `requirements.txt`. `requirements-dev.txt` holds dev tooling and is compiled alongside `pyproject.toml`.

## PYTHONPATH Requirement

All `pytest` and `mypy` invocations need `PYTHONPATH=src` — the package is not installed editably by default:

```bash
PYTHONPATH=src pytest
PYTHONPATH=src mypy src
```

The helper scripts (`scripts/test.sh`, `scripts/typecheck.sh`) handle this automatically.

## Python Version Fallback (uv)

If the required Python version is missing, use `uv` to fetch and run it instead of changing system Python. Read the target version from the repo tech config (`.python-version`) rather than hardcoding it.

```bash
PY_VER="$(cat .python-version)"
uv python install "$PY_VER"
uv pip install -r requirements-dev.lock --python "$PY_VER"
PYTHONPATH=src uv run --python "$PY_VER" pytest
PYTHONPATH=src uv run --python "$PY_VER" mypy src
```

## Formatter Split — Critical Gotcha

Black is the **formatter**; Ruff is the **linter only**. `ruff format` is intentionally disabled to avoid conflicts with Black. Never use `ruff format`.

```bash
black src tests          # format
ruff check --fix src tests  # lint + autofix
```

`./scripts/format.sh` runs both in the correct order. `./scripts/format.sh --check src tests` is the CI-equivalent check.

## Developer Commands

| Task | Script | Direct equivalent |
|---|---|---|
| Format + lint | `./scripts/format.sh` | `black src tests && ruff check --fix src tests` |
| Format check only | `./scripts/format.sh --check src tests` | `black --check src tests && ruff check src tests` |
| Type check | `./scripts/typecheck.sh` | `PYTHONPATH=src mypy src` |
| Run all tests | `./scripts/test.sh` | `PYTHONPATH=src pytest` |
| Run focused tests | `./scripts/test.sh tests/test_config.py` | `PYTHONPATH=src pytest tests/test_config.py` |
| Run by keyword | `./scripts/test.sh -k "test_config"` | `PYTHONPATH=src pytest -k "test_config"` |
| Regenerate lockfiles | `./scripts/compile-deps.sh` | — |
| Start app locally | `./scripts/start.sh` | requires `.env` with Tautulli values |

**PR check order:** format → typecheck → test. CI gates on all three.

## Dependency Changes

If you modify the dependencies in `pyproject.toml` or `requirements-dev.txt`, regenerate and commit the lockfiles:

```bash
./scripts/compile-deps.sh
```

Never edit `requirements*.lock` files directly.

## Dev Environment

Devcontainer (`.devcontainer/`) is the canonical environment — all tool versions are pinned there. Host-native development is optional; if used, install from `requirements-dev.lock`:

```bash
pip install -r requirements-dev.lock
```

Fallback (no VS Code Dev Containers):

```bash
docker compose -f docker-compose.dev.yml up -d --build
docker compose -f docker-compose.dev.yml exec app bash
```

## Branch & PR Conventions

Flow: `feature/*` → `develop` → `release/*` → `main`

- Always branch from `develop`, target PRs at `develop`
- Hotfixes: branch from `main`, target `main`, use `hotfix/<description>`
- **PR titles must use a conventional commit prefix** — CI blocks merges on violations. Format: `<type>[optional scope][optional !]: <description>`
  - Valid types include: `feat`, `fix`, `bugfix`, `hotfix`, `docs`, `refactor`, `chore`, `test`, `ci`, `deps`, `improve`, `perf`, `security`, `breaking`, `release`, `wip`
  - `!` suffix (e.g. `feat!:`) marks breaking changes and adds the `breaking` label automatically

## Source Layout

```
src/
  app.py               # main orchestration logic
  config.py            # Pydantic v2 config loader (env vars, YAML, Docker secrets)
  media_source.py      # backend-neutral contract every media source implements
  tautulli_client.py   # Tautulli source (Plex only)
  tracearr_client.py   # Tracearr source (Plex, Jellyfin, Emby): regroups and enriches
  discord_client.py    # Discord webhook client, builds per-server deep links
  health_server.py     # optional GET /health endpoint (scheduled mode only)
  scheduler.py         # APScheduler daemon mode
  logging_config.py    # logging setup
tests/                 # mirrors src/ module structure; all tests use mocked HTTP
configs/config.yml     # runtime config (generated from template on first container start)
```

## Media Sources

Two backends implement `MediaSourceClient` (`src/media_source.py`):

- **Tracearr** — Plex, Jellyfin, Emby. **This is where new media-source features go**; gate them on `media_source` rather than holding them back for parity with Tautulli.
- **Tautulli** — Plex only, **in maintenance**: fixes yes, new features no. It stays because it needs no extra infrastructure, it is the only source that auto-detects the media server id, and it is the independent oracle for validating Tracearr's reconstructed grouping.

`media_source` defaults to `tautulli` for backward compatibility — changing that default is a breaking change.

## Container Path Contracts

Keep container-side paths fixed; only vary host-side mounts:

- Config: `/app/configs/config.yml`
- Logs: `/app/logs`
- Secrets: `/run/secrets` — any config value that starts with `/` is read as a file, so `TRACEARR_API_KEY=/run/secrets/tracearr_api_key` works as-is

New config keys are appended to an existing `config.yml` on startup (`sync_missing_config_keys`). Without that, a key added to the template would never reach an install that predates it, and the matching environment variable would silently do nothing.

## Testing Notes

- Pytest always runs with `--cov=src --cov-branch` — coverage reports are generated every run (`htmlcov/`, `coverage.xml`)
- Two markers: `unit` and `integration` (integration tests use mocked HTTP, no live services needed)
- `tests/*` has `S101` (assert) ignored by Ruff — don't add `# noqa` for asserts in test files
