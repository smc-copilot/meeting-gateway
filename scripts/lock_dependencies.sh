#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/.."
# Requires registry access; this RC was produced in an offline environment.
uv lock --python 3.12
uv sync --frozen --group dev
uv run pytest
uv run ruff format app tests integration/backend examples scripts
uv run ruff check --fix app tests integration/backend examples scripts
uv run pytest
uv run ruff check app tests integration/backend examples scripts
# Review and commit uv.lock and formatting changes before production promotion.
