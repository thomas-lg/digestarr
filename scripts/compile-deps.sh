#!/bin/sh
# Regenerate requirements.txt and requirements-dev.txt.
#
# Runtime dependencies are declared in requirements.in — that is the single source of
# truth, and pyproject.toml reads it via [tool.setuptools.dynamic].
# requirements-dev.in holds dev-only tooling and pulls requirements.in in with -r, so
# the dev lock is a superset of the runtime lock.
#
# Run this after modifying requirements.in or requirements-dev.in and commit the result.
#
# Two properties below are load-bearing for Dependabot, which recompiles these locks
# on its own PRs — do not change them without rerunning the simulation in the PR that
# introduced them (thomas-lg/digestarr#171):
#
#   1. The .in/.txt naming. Dependabot only fetches *.txt and *.in, and only treats a
#      .txt as pip-compile output when a sibling *.in exists. Files named *.lock are
#      invisible to it, so it bumps the constraint and leaves the lock stale.
#   2. One .in input per lock. Dependabot rebuilds the command as
#      `pip-compile <options from the .txt header> -P <dep>==<version> <the .in>` — a
#      single source file. Passing a second input here (say pyproject.toml) would make
#      its command differ from ours, and it would silently drop everything that input
#      contributed.
#
# A third property is outside our control: Dependabot compiles with its own pip-tools,
# the CI recheck uses the one pinned in requirements-dev.txt. A pip-tools release that
# changes the header or annotation format can therefore desync a Dependabot PR from the
# CI recheck. If a pip-tools bump ever fails this way, recompile it by hand once.

set -e

export LC_ALL=C
export LANG=C

cd "$(dirname "$0")/.."

echo "📦 Compiling requirements.txt..."
pip-compile requirements.in \
    --output-file requirements.txt \
    --annotate \
    --strip-extras \
    --quiet

echo "📦 Compiling requirements-dev.txt..."
pip-compile requirements-dev.in \
    --output-file requirements-dev.txt \
    --annotate \
    --strip-extras \
    --quiet

echo "✅ Lockfiles updated. Remember to commit requirements.txt and requirements-dev.txt."
