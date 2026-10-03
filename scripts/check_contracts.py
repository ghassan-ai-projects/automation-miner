"""Fail when retired schema contracts or orphaned schema models return."""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "src" / "automation_miner"
SCHEMA_PACKAGE = SOURCE_ROOT / "schemas"
SCHEMA_EXPORTS = SCHEMA_PACKAGE / "__init__.py"
STATE_PATH = SOURCE_ROOT / "graph" / "state.py"
RETIRED_SYMBOLS = ("DraftBatch", "draft_prompt")
IGNORED_SCHEMA_SYMBOLS = {"ArtifactModel"}


def _source_text() -> str:
    """Production source, excluding the re-export list that names every schema."""
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in SOURCE_ROOT.rglob("*.py")
        if path != SCHEMA_EXPORTS
    )


def _typed_dict_fields(path: Path) -> dict[str, set[str]]:
    """Return declared fields for every TypedDict class in ``path``."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    fields: dict[str, set[str]] = {}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        if not any(
            isinstance(base, ast.Name) and base.id == "TypedDict" for base in node.bases
        ):
            continue
        fields[node.name] = {
            statement.target.id
            for statement in node.body
            if isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
        }
    return fields


def main() -> int:
    text = _source_text()
    errors: list[str] = []

    for symbol in RETIRED_SYMBOLS:
        if re.search(rf"\b{re.escape(symbol)}\b", text):
            errors.append(f"retired symbol is still referenced: {symbol}")

    defined: set[str] = set()
    for module in sorted(SCHEMA_PACKAGE.glob("*.py")):
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        defined |= {
            node.name
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name not in IGNORED_SCHEMA_SYMBOLS
        }
    for symbol in sorted(defined):
        occurrences = len(re.findall(rf"\b{re.escape(symbol)}\b", text))
        if occurrences < 2:
            errors.append(f"schema contract has no production owner: {symbol}")

    # StateGraph channels are contracts too. A declared channel must have a
    # production read or write outside its TypedDict declaration; otherwise it
    # is dead shared state that can silently drift from the graph.
    production_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in SOURCE_ROOT.rglob("*.py")
        if path != STATE_PATH
    )
    for class_name, fields in _typed_dict_fields(STATE_PATH).items():
        for field in sorted(fields):
            if not re.search(rf"\b{re.escape(field)}\b", production_text):
                errors.append(
                    f"TypedDict channel has no production owner: {class_name}.{field}"
                )

    if errors:
        print("Contract check failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    channel_count = sum(len(fields) for fields in _typed_dict_fields(STATE_PATH).values())
    print(
        f"Contract check passed: {len(defined)} schema contracts and "
        f"{channel_count} state channels have live owners."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
