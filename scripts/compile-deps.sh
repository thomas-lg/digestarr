#!/bin/sh
# Regenerate requirements.lock and requirements-dev.lock.
#
# Runtime dependencies are declared in pyproject.toml ([project].dependencies) —
# that is the single source of truth, so pyproject.toml is the input here.
# requirements-dev.txt holds dev-only tooling and is compiled together with
# pyproject.toml so the dev lock is a superset of the runtime lock.
#
# Run this after modifying pyproject.toml or requirements-dev.txt and commit the result.

set -e

export LC_ALL=C
export LANG=C

cd "$(dirname "$0")/.."

echo "📦 Compiling requirements.lock..."
pip-compile pyproject.toml \
    --output-file requirements.lock \
    --annotate \
    --strip-extras \
    --quiet

echo "📦 Compiling requirements-dev.lock..."
pip-compile pyproject.toml requirements-dev.txt \
    --output-file requirements-dev.lock \
    --annotate \
    --strip-extras \
    --quiet

echo "✅ Lockfiles updated. Remember to commit requirements.lock and requirements-dev.lock."
