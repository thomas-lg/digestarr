#!/bin/sh
# Regenerate requirements.txt and requirements-dev.txt.
#
# Runtime dependencies are declared in pyproject.toml ([project].dependencies) —
# that is the single source of truth, so pyproject.toml is the input here.
# requirements-dev.in holds dev-only tooling and is compiled together with
# pyproject.toml so the dev lock is a superset of the runtime lock.
#
# Run this after modifying pyproject.toml or requirements-dev.in and commit the result.
#
# The .in/.txt naming is the pip-tools convention and is load-bearing: Dependabot only
# recompiles a lockfile when it is named *.txt and has either a sibling *.in or an
# --output-file=<its own name> header. Renaming these files back to *.lock would make
# Dependabot bump the constraints without regenerating the locks, failing the CI check.

set -e

export LC_ALL=C
export LANG=C

cd "$(dirname "$0")/.."

echo "📦 Compiling requirements.txt..."
pip-compile pyproject.toml \
    --output-file requirements.txt \
    --annotate \
    --strip-extras \
    --quiet

echo "📦 Compiling requirements-dev.txt..."
pip-compile pyproject.toml requirements-dev.in \
    --output-file requirements-dev.txt \
    --annotate \
    --strip-extras \
    --quiet

echo "✅ Lockfiles updated. Remember to commit requirements.txt and requirements-dev.txt."
