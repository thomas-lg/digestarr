# Copilot Instructions

## Project Overview

**plex-releases-summary** is a lightweight Docker container that fetches recently added media from Plex via the Tautulli API and posts rich Discord embeds summarising new movies, TV shows, episodes, and music. It runs either on a schedule (APScheduler) or as a one-shot (`RUN_ONCE=true`).

## Tech Stack

- **Python 3.14** — minimum required version
- **Pydantic v2** — config validation (`src/config.py`)
- **APScheduler** — scheduled execution (`src/scheduler.py`)
- **discord-webhook** — Discord embed posting (`src/discord_client.py`)
- **requests** — Tautulli HTTP client (`src/tautulli_client.py`)
- **Black** — formatter (line length 120)
- **Ruff** — linter (see `pyproject.toml` for enabled rule sets)
- **mypy** — type checker (strict optional, `check_untyped_defs`)
- **pytest + pytest-cov** — test runner with branch coverage

## Source Layout

```
src/
  app.py               # Entry point, wires scheduler/run-once
  config.py            # Pydantic config model, loaded from config.yml
  tautulli_client.py   # Fetches recently added media from Tautulli
  discord_client.py    # Builds and sends Discord embeds
  scheduler.py         # APScheduler wrapper
  logging_config.py    # Logging setup
tests/
  test_*.py            # Unit tests (pytest markers: unit, integration)
```

## Branching Strategy

```
feature/* ──► develop ──► release/* ──► main
```

- New work targets `develop` via `feature/*` branches
- `main` is the stable production branch (builds `latest` Docker image)
- Hotfixes use `hotfix/<description>` branched from `main`
- Dependabot PRs target `develop`

## Code Style

- Format with Black (`./scripts/format.sh`)
- Lint with Ruff (`ruff check --fix`)
- Type-check with mypy (`./scripts/typecheck.sh`)
- Add type hints to all public functions and methods
- Use `%`-style logging (not f-strings) in log calls — enforced by Ruff rule `G`
- Never use bare `assert` outside tests; raise explicit exceptions instead

## Testing

- Run all tests: `./scripts/test.sh`
- Unit tests mock at the class level; integration tests mock only at the HTTP boundary
- Mark tests with `@pytest.mark.unit` or `@pytest.mark.integration`
- All new behaviour must be covered by tests

## Dependency / Lockfile Management

- Runtime deps: declared in `pyproject.toml` (`[project].dependencies`) → compiled to `requirements.lock`
- Dev deps: `requirements-dev.txt` (dev tooling only) → compiled with `pyproject.toml` to `requirements-dev.lock`
- `pyproject.toml` is the single source of truth for runtime constraints — never duplicate them in a requirements file
- After changing `pyproject.toml` or `requirements-dev.txt`, regenerate and commit the lockfiles:
  ```bash
  ./scripts/compile-deps.sh
  ```
- Docker and the devcontainer install from the lockfiles, not the loose requirements

## Pull Requests

When creating a pull request, always follow the structure defined in `.github/pull_request_template.md`:
- Fill in the **Summary** section with a clear description of what the PR does and why
- Complete the **Checklist** items that apply
- Fill in the **Related issues** section if applicable

PR titles must follow [Conventional Commits](https://www.conventionalcommits.org/) (e.g. `feat: add X`, `fix: correct Y`, `chore: update Z`).

Valid types are the **keys** from `.github/conventional-commit-types.json` (not the label values):
`feat`, `improve`, `perf`, `fix`, `bugfix`, `hotfix`, `revert`, `breaking`, `security`, `docs`, `refactor`, `style`, `cleanup`, `chore`, `test`, `build`, `ci`, `actions`, `deps`, `deprecate`, `release`, `wip`

> ⚠️ The JSON values are GitHub label names — they are **not** valid commit types and must never be used as PR title prefixes. The following are label names only and have no valid use as a prefix:
> - `feature` → use `feat`
> - `enhancement` → use `improve` or `perf`
> - `documentation` → use `docs`
> - `github-actions` → use `ci` or `actions`
> - `dependencies` → use `deps`
> - `deprecated` → use `deprecate`

Append `!` before the colon to denote a breaking change (e.g. `feat!: redesign config schema`).
