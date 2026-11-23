set shell := ["sh", "-cu"]

setup:
    uv sync --locked

test:
    uv run pytest -q

lint:
    uv run ruff check .
    python3 scripts/profiles.py lint plugins/polyagent/skills/polyagent/profiles/*

typecheck:
    uv run pyright

verify: lint typecheck test

# Assemble the plugin and both marketplace catalogs in dist/marketplace.
build:
    python3 scripts/package.py build

# Ask real Codex and Claude Code models to apply the skill to the eval cases. Not part of verify.
[positional-arguments]
eval *args:
    uv run python tests/eval/run.py "$@"

# Preview only; preparation never creates tags or publishes.
release:
    python3 scripts/release.py

release-apply:
    python3 scripts/release.py --apply

# Publish the reviewed release commit: source tag, marketplace branch and GitHub Release.
[positional-arguments]
release-publish *args:
    python3 scripts/release_workflow.py "$@"
