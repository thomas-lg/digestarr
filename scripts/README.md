# Scripts Directory

These scripts are thin wrappers for contributor workflows.

All scripts work both inside the devcontainer and on the host, provided the required dependencies are installed. The devcontainer is the recommended setup as it provides a ready-made environment.

## Available Scripts

### 🐳 `dev-container-shell.sh` - Enter Dev Container Shell

Start the development compose stack and open a shell in the app container.

> **Requires Docker** — the Docker CLI and a running Docker daemon must be available on `PATH`. The script will exit with a clear error message if either is missing.

```bash
./scripts/dev-container-shell.sh
./scripts/dev-container-shell.sh pytest -q
```

### ▶️ `start.sh` - Start Application

Run the app locally with optional `.env` loading.

```bash
cp .env.example .env
# Edit .env with your values, then:
./scripts/start.sh                       # Load .env if present
ENV_FILE=.env.local ./scripts/start.sh  # Use custom env file
```

Required environment variables for default config placeholders:

- `TAUTULLI_URL`
- `TAUTULLI_API_KEY`

### 🧪 `test.sh` - Run Tests

Run pytest with coverage.

```bash
./scripts/test.sh                           # Run default test suite + coverage
./scripts/test.sh tests/test_config.py      # Run specific test file
./scripts/test.sh -k "test_config"          # Run tests matching pattern
```

### 🎨 `format.sh` - Format and Lint

Run Black and Ruff.

```bash
./scripts/format.sh                          # Black + Ruff --fix (default: src tests)
./scripts/format.sh src                      # Format/lint src only
./scripts/format.sh --check src tests        # Check mode (no writes)
```

### 🧠 `typecheck.sh` - Type Checking

Run mypy.

```bash
./scripts/typecheck.sh                       # Type check default target: src
./scripts/typecheck.sh src                   # Type check src explicitly
./scripts/typecheck.sh src/config.py         # Type check specific file
```

### 📦 `compile-deps.sh` - Regenerate Lockfiles

Recompile `requirements.lock` and `requirements-dev.lock`.

Runtime constraints live in `pyproject.toml` (`[project].dependencies`), which is the
input for both locks; `requirements-dev.txt` adds dev-only tooling on top. Run this
after modifying either file and commit the updated lockfiles.

```bash
./scripts/compile-deps.sh
```

### 🧹 `clean.sh` - Clean Local Artifacts

Remove generated test/coverage/cache files.

```bash
./scripts/clean.sh
```

## Quick Reference

| Task         | Command                            |
| ------------ | ---------------------------------- |
| Dev shell    | `./scripts/dev-container-shell.sh` |
| Start app    | `./scripts/start.sh`               |
| Run tests    | `./scripts/test.sh`                |
| Format       | `./scripts/format.sh`              |
| Type check   | `./scripts/typecheck.sh`           |
| Compile deps | `./scripts/compile-deps.sh`        |
| Clean        | `./scripts/clean.sh`               |

## Notes

- For app runtime and deployment, use [docker-compose.yml](../docker-compose.yml) with the published image.
- Contributor setup and daily workflow are documented in [CONTRIBUTING.md](../CONTRIBUTING.md).
