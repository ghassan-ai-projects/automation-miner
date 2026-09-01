.PHONY: sync lint test type-check contract-check build ci-check dry-run

sync:
	uv sync --all-extras

test:
	uv run pytest

lint:
	uv run ruff check src tests scripts

type-check:
	uv run mypy

contract-check:
	uv run python scripts/check_contracts.py

build:
	uv build

ci-check: lint test type-check contract-check build

dry-run:
	uv run automation-miner mine "German healthcare back office" --dry-run --workspace /tmp/am-smoke
