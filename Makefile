.PHONY: sync test lint dry-run

sync:
	uv sync

test:
	uv run pytest

lint:
	uv run ruff check src tests

dry-run:
	uv run automation-miner mine "German healthcare back office" --dry-run --workspace /tmp/am-smoke
