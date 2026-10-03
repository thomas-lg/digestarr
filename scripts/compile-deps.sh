#!/bin/sh
# Regenerate requirements.txt and requirements-dev.txt from pyproject.toml.
#
# Dependency constraints live in pyproject.toml ([project] dependencies and the "dev"
# extra). Run this after changing them and commit both lockfiles.
#
# Renovate recompiles the locks the same way on its own PRs: it reads the command back
# from each lockfile header, then runs this script with the toolchain pinned in
# requirements-dev.txt (postUpgradeTasks in renovate.json). `python -m piptools` makes
# sure that pinned pip-tools is the one used, whatever `pip-compile` is first on PATH.

set -e

export LC_ALL=C
export LANG=C

cd "$(dirname "$0")/.."

echo "📦 Compiling requirements.txt..."
python -m piptools compile pyproject.toml \
    --output-file requirements.txt \
    --strip-extras \
    --quiet

echo "📦 Compiling requirements-dev.txt..."
python -m piptools compile pyproject.toml \
    --extra dev \
    --output-file requirements-dev.txt \
    --strip-extras \
    --quiet

echo "✅ Lockfiles updated. Remember to commit requirements.txt and requirements-dev.txt."
