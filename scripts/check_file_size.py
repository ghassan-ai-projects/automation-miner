"""Fail when any Python file exceeds the project's 300-line ceiling.

Small files keep each module to one responsibility and keep review diffs
legible. The ceiling applies to production code, scripts, and tests alike.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_LINES = 300
CHECKED = ("src", "scripts", "tests")


def oversized(root: Path = ROOT, limit: int = MAX_LINES) -> list[tuple[Path, int]]:
    found: list[tuple[Path, int]] = []
    for folder in CHECKED:
        for path in sorted((root / folder).rglob("*.py")):
            count = len(path.read_text(encoding="utf-8").splitlines())
            if count > limit:
                found.append((path.relative_to(root), count))
    return found


def main() -> int:
    offenders = oversized()
    if offenders:
        print(f"File size check failed: {len(offenders)} file(s) exceed {MAX_LINES} lines.")
        for path, count in offenders:
            print(f"- {path}: {count} lines")
        return 1
    print(f"File size check passed: every Python file is at most {MAX_LINES} lines.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
