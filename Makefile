.PHONY: sync lint test build ci-check dry-run

sync:
	uv sync --all-extras

test:
	uv run pytest

lint:
	uv run ruff check src tests

build:
	uv build

ci-check: lint test build

dry-run:
	uv run automation-miner mine "German healthcare back office" --dry-run --workspace /tmp/am-smoke
