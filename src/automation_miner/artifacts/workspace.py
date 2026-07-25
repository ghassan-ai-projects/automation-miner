"""Workspace layout: run directories, JSON artifacts, global AM numbering.

Layout (per DESIGN.md / spec 03):
    <workspace>/registry.json
    <workspace>/runs/<YYYY-MM-DD>_<domain-slug>/...
    <workspace>/opps/<domain-slug>/AM-XXX-<slug>.md
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

_AM_RE = re.compile(r"AM-(\d+)")
_AM_ID_RE = re.compile(r"(?:AM-)?(\d+)", re.IGNORECASE)
_RUN_ID_RE = re.compile(r"\d{4}-\d{2}-\d{2}_[a-z0-9]+(?:-[a-z0-9]+)*")


def default_workspace() -> Path:
    """Default workspace: $MINER_WORKSPACE or ./mining-workspace."""
    import os

    return Path(os.environ.get("MINER_WORKSPACE", "mining-workspace"))


@dataclass
class Workspace:
    root: Path

    @property
    def runs_dir(self) -> Path:
        return self.root / "runs"

    @property
    def opps_dir(self) -> Path:
        return self.root / "opps"

    @property
    def registry_path(self) -> Path:
        return self.root / "registry.json"

    @property
    def cache_dir(self) -> Path:
        """Durable cache root (digests), so re-mining a knowledge base is free."""
        return self.root / ".cache"

    def ensure(self) -> None:
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.opps_dir.mkdir(parents=True, exist_ok=True)

    def new_run_dir(self, domain_slug: str) -> Path:
        """Create runs/YYYY-MM-DD_<slug> (suffix -2, -3... if repeated today)."""
        self.ensure()
        base = f"{datetime.now():%Y-%m-%d}_{domain_slug}"
        n = 1
        while True:
            suffix = "" if n == 1 else f"-{n}"
            run_dir = self.runs_dir / f"{base}{suffix}"
            try:
                run_dir.mkdir()
                break
            except FileExistsError:
                n += 1
        (run_dir / "layers").mkdir()
        (run_dir / "drafts").mkdir()
        return run_dir

    def opp_dir(self, domain_slug: str) -> Path:
        path = self.opps_dir / domain_slug
        path.mkdir(parents=True, exist_ok=True)
        return path

    def next_am_number(self) -> int:
        """Global sequential numbering: max existing AM id + 1 (start at 1)."""
        return self._highest_am_number() + 1

    def reserve_am_numbers(self, count: int) -> list[int]:
        """Atomically reserve a monotonic AM-ID range across concurrent runs."""
        if count < 1:
            raise ValueError("count must be at least 1")
        import fcntl

        self.ensure()
        lock_path = self.root / ".am-id.lock"
        counter_path = self.root / ".am-counter"
        with lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                try:
                    counter = int(counter_path.read_text(encoding="utf-8").strip())
                except (FileNotFoundError, ValueError):
                    counter = 0
                start = max(counter, self._highest_am_number()) + 1
                end = start + count - 1
                write_text(counter_path, f"{end}\n")
                return list(range(start, end + 1))
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _highest_am_number(self) -> int:
        highest = 0
        if self.opps_dir.exists():
            for f in self.opps_dir.rglob("AM-*.md"):
                m = _AM_RE.match(f.name)
                if m:
                    highest = max(highest, int(m.group(1)))
        if self.registry_path.is_file():
            try:
                registry = read_json(self.registry_path)
            except (OSError, ValueError):
                registry = {}
            for entry in registry.get("entries", []) if isinstance(registry, dict) else []:
                if isinstance(entry, dict):
                    match = _AM_RE.fullmatch(str(entry.get("i", "")))
                    if match:
                        highest = max(highest, int(match.group(1)))
        return highest

    def list_runs(self) -> list[str]:
        if not self.runs_dir.exists():
            return []
        return sorted(p.name for p in self.runs_dir.iterdir() if p.is_dir())

    def find_opportunity(self, value: str) -> tuple[str, Path] | None:
        """Find one brief by a validated, normalized AM identifier."""
        am_id = normalize_am_id(value)
        matches = sorted(self.opps_dir.rglob(f"{am_id}-*.md")) if self.opps_dir.exists() else []
        return (am_id, matches[0]) if matches else None

    def run_report_path(self, run_id: str) -> Path:
        """Return a report path for a syntactically valid direct run child."""
        return self._run_file(run_id, "report.md")

    def run_summary_path(self, run_id: str) -> Path:
        """Return the compact summary path for a validated run id."""
        return self._run_file(run_id, "summary.json")

    def _run_file(self, run_id: str, name: str) -> Path:
        if not _RUN_ID_RE.fullmatch(run_id):
            raise ValueError(f"Invalid run id: {run_id!r}")
        return self.runs_dir / run_id / name


def normalize_am_id(value: str) -> str:
    """Normalize ``2``/``AM-2`` to ``AM-002`` and reject pattern syntax."""
    match = _AM_ID_RE.fullmatch(value.strip())
    if match is None or int(match.group(1)) < 1:
        raise ValueError(f"Invalid opportunity id: {value!r}")
    return f"AM-{int(match.group(1)):03d}"


def write_text(path: Path, text: str) -> None:
    """Atomically replace a UTF-8 text artifact in its destination directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        temp_path.replace(path)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise


def write_json(path: Path, payload: BaseModel | dict[str, Any] | list[Any]) -> None:
    """Persist a JSON artifact (pydantic model or plain data)."""
    if isinstance(payload, BaseModel):
        text = payload.model_dump_json(indent=2)
    else:
        text = json.dumps(payload, indent=2, ensure_ascii=False, default=str)
    write_text(path, text + "\n")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))
