# Contributing to Digestarr

Thank you for contributing to Digestarr.

## Table of Contents

- [Contributing to Digestarr](#contributing-to-digestarr)
  - [Table of Contents](#table-of-contents)
  - [Branching Strategy](#branching-strategy)
  - [Getting Started](#getting-started)
  - [Development Setup](#development-setup)
    - [Prerequisites](#prerequisites)
    - [Canonical Workflow (Devcontainer)](#canonical-workflow-devcontainer)
    - [Optional Host Workflow](#optional-host-workflow)
  - [Code Style](#code-style)
  - [Testing](#testing)
  - [Pull Request Process](#pull-request-process)
  - [Production Image and Deployment](#production-image-and-deployment)

## Branching Strategy

This repository uses a structured Git flow:

```text
feature/* ──► develop ──► release/* ──► main
                ▲                        │
                └──── nightly sync ◄─────┘
```

| Branch | Purpose | Merges into |
| --- | --- | --- |
| `feature/*` | New features and fixes | `develop` |
| `develop` | Integration branch, builds `develop` Docker image | `release/*` |
| `release/*` | Release preparation | `main` |
| `main` | Stable production branch, builds `latest` Docker image | — |

**Release branches** use the `release/<name>` convention — preferably date-based (e.g. `release/2026-02-22`) or version-based (e.g. `release/1.0`). The tag version (`vX.Y.Z`) is computed automatically by release-drafter from merged PR labels; confirm or adjust it when publishing the draft release on GitHub.

**Hotfixes** use a `hotfix/<short-description>` branch cut from `main`, opened as a PR targeting `main`. Follow the same conventional commit title and labeling rules as normal PRs (see [Pull Request Process](#pull-request-process)), applying the `hotfix` label if it exists. The nightly sync backports `main` → `develop` automatically at 02:00 UTC; conflicts open a PR targeting `develop` for manual resolution.

> **Repository setup required:** the nightly sync needs a `SYNC_TOKEN` repository secret (fine-grained PAT with "Contents: Read & Write" and "Pull requests: Read & Write" scopes) to push directly to the protected `develop` branch. See the prerequisites comment at the top of [`.github/workflows/sync-develop.yml`](.github/workflows/sync-develop.yml) for details.

**Dependabot** PRs target `develop` and flow through the normal release process.

## Getting Started

1. Fork the repository
2. Clone your fork locally
3. Create a `feature/*` branch from `develop`
4. Make your changes and open a pull request targeting `develop`

## Development Setup

### Prerequisites

- Docker
- VS Code + Dev Containers extension
- Git

### Canonical Workflow (Devcontainer)

Open the project in the devcontainer:

```text
Command Palette → Dev Containers: Reopen in Container
```

Dependencies are installed in the devcontainer image (built from [.devcontainer/Dockerfile.dev](.devcontainer/Dockerfile.dev)), so the environment is ready to use as soon as the container starts.

If Dev Containers is not available, [docker-compose.dev.yml](docker-compose.dev.yml) uses the same image and provides an equivalent environment:

```bash
docker compose -f docker-compose.dev.yml up -d --build
docker compose -f docker-compose.dev.yml exec app bash
# or using the helper script:
./scripts/dev-container-shell.sh
```

Inside the devcontainer, run checks with either direct commands or helper scripts:

```bash
./scripts/format.sh
./scripts/typecheck.sh
./scripts/test.sh
```

Equivalent direct commands:

```bash
black src tests
ruff check --fix src tests
PYTHONPATH=src mypy src
PYTHONPATH=src pytest --cov=src --cov-branch --cov-report=xml --cov-report=term-missing --cov-report=html
```

### Optional Host Workflow

Host-native development is optional and not the primary workflow. If you use it, mirror the same Python/tool versions as the devcontainer.

Install all dependencies:

```bash
pip install -r requirements-dev.lock
```

Copy the example environment file and fill in your values:

```bash
cp .env.example .env
# Edit .env with your Tautulli URL and API key
```

Use the same app start command as devcontainer:

```bash
./scripts/start.sh
```

## Code Style

- Python 3.14
- Black for formatting
- Ruff for linting
- mypy for type checking
- Type hints for public functions/methods

## Testing

Run all tests:

```bash
./scripts/test.sh
```

Run a subset:

```bash
./scripts/test.sh tests/test_config.py
./scripts/test.sh -k "test_config"
```

## Pull Request Process

Before submitting:

1. Run formatting/lint checks

   ```bash
   ./scripts/format.sh --check src tests
   ```

2. Run type checks

   ```bash
   ./scripts/typecheck.sh
   ```

3. Run tests

   ```bash
   ./scripts/test.sh
   ```

4. If you changed the dependencies in `pyproject.toml`, or `requirements-dev.txt`, regenerate the lockfiles and commit them:

   ```bash
   ./scripts/compile-deps.sh
   ```

5. Update docs when behavior/configuration changes

PR expectations:

- Keep PRs focused
- **Use a conventional commit prefix in the PR title** (e.g. `feat: ...`, `fix: ...`, `docs: ...`, `feat!: ...`). The CI title check validates the prefix directly — the PR will be blocked if the title doesn't match the format `<type>[optional scope][optional !]: <description>`, where the optional `!` (after the type or scoped type) marks a breaking change.

  Valid types: `feat`, `improve`, `perf`, `fix`, `bugfix`, `hotfix`, `revert`, `breaking`, `security`, `docs`, `refactor`, `style`, `cleanup`, `chore`, `test`, `build`, `ci`, `actions`, `deps`, `deprecate`, `release`, `wip`

  A label is also automatically applied from the prefix by a separate workflow:

  | Prefix                                                   | Label applied            |
  | -------------------------------------------------------- | ------------------------ |
  | `feat`                                                   | `feature`                |
  | `improve`, `perf`                                        | `enhancement`            |
  | `fix`, `bugfix`, `hotfix`, `revert`                      | `fix`                    |
  | `breaking`                                               | `breaking`               |
  | `security`                                               | `security`               |
  | `docs`                                                   | `documentation`          |
  | `refactor`, `style`, `cleanup`, `chore`, `test`, `build` | `chore`                  |
  | `ci`, `actions`                                          | `github-actions`         |
  | `deps`                                                   | `dependencies`           |
  | `deprecate`                                              | `deprecated`             |
  | `release`                                                | `release`                |
  | `wip`                                                    | `wip`                    |
  | `feat!`, `fix!`, … (breaking)                            | above label + `breaking` |

- Ensure CI passes

## Production Image and Deployment

This repository uses two separate workflows for CI/CD and release management:

- Production build definition: `Dockerfile`
- CI/CD pipeline: `.github/workflows/ci.yml` (quality checks, tests, Docker build & push)
- Release drafter: `.github/workflows/draft-release.yml` (draft release notes on push to `main`; publish via `workflow_dispatch`)
- Deployment example: `docker-compose.yml`

The pipeline gates Docker image publishing on passing quality and test checks. Images are published to `ghcr.io/thomas-lg/digestarr` with the following tags:

| Tag | When |
| --- | --- |
| `latest` | Push to `main` |
| `develop` | Push to `develop` |
| `vX.Y.Z` | Version tag (`v*`) |
| `sha-<shortsha>` | Push to `main` (traceability; short commit SHA) |

Contributors should not use production compose files as the day-to-day development environment.
