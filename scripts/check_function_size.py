"""Fail when any function or method exceeds the 25-line ceiling (production code in src/).

Counted lines are code lines from ``def`` to the end of the body; the
docstring, blank lines, and comment-only lines are not counted. Long prompt
text belongs in module constants, and long logic belongs in named helpers.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_LINES = 25
CHECKED = ("src",)


def _docstring_lines(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[int]:
    first = node.body[0] if node.body else None
    if (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    ):
        return set(range(first.lineno, (first.end_lineno or first.lineno) + 1))
    return set()


def code_lines(node: ast.FunctionDef | ast.AsyncFunctionDef, source: list[str]) -> int:
    start = min([node.lineno, *(d.lineno for d in node.decorator_list)])
    skip = _docstring_lines(node)
    return sum(
        1
        for number in range(start, (node.end_lineno or node.lineno) + 1)
        if number not in skip
        and source[number - 1].strip()
        and not source[number - 1].strip().startswith("#")
    )


def oversized(root: Path = ROOT, limit: int = MAX_LINES) -> list[tuple[str, str, int]]:
    found: list[tuple[str, str, int]] = []
    for folder in CHECKED:
        for path in sorted((root / folder).rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            source = text.splitlines()
            for node in ast.walk(ast.parse(text)):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    count = code_lines(node, source)
                    if count > limit:
                        found.append((str(path.relative_to(root)), node.name, count))
    return found


def main() -> int:
    offenders = oversized()
    if offenders:
        print(f"Function size check failed: {len(offenders)} function(s) exceed {MAX_LINES} lines.")
        for path, name, count in sorted(offenders, key=lambda item: -item[2]):
            print(f"- {path}::{name}: {count} lines")
        return 1
    print(f"Function size check passed: every function is at most {MAX_LINES} code lines.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
