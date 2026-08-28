"""Workspace layout: run directories, JSON artifacts, global AM numbering.

Layout:
    <workspace>/registry.json
    <workspace>/runs/<YYYY-MM-DD>_<domain-slug>/...
    <workspace>/opps/<domain-slug>/AM-XXX-<slug>.md
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

_AM_RE = re.compile(r"AM-(\d+)")
_AM_ID_RE = re.compile(r"(?:AM-)?(\d+)", re.IGNORECASE)
_RUN_ID_RE = re.compile(r"\d{4}-\d{2}-\d{2}_[a-z0-9]+(?:-[a-z0-9]+)*")
_BRIEF_SOURCE_RE = re.compile(r"^source:\s*(.+)$", re.MULTILINE)


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
        """Return the next number without reserving it."""
        return max(self._highest_am_number(), self._counter_value()) + 1

    def reserve_am_numbers(self, count: int) -> list[int]:
        """Atomically reserve a monotonic AM-ID range across concurrent runs."""
        if count < 1:
            raise ValueError("count must be at least 1")
        self.ensure()
        database = self.root / ".am-ids.sqlite3"
        with _legacy_counter_lock(self.root):
            connection = sqlite3.connect(database, timeout=30.0, isolation_level=None)
            try:
                connection.execute("PRAGMA busy_timeout = 30000")
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS am_counter (id INTEGER PRIMARY KEY CHECK (id = 1), value INTEGER NOT NULL)"
                )
                row = connection.execute(
                    "SELECT value FROM am_counter WHERE id = 1"
                ).fetchone()
                stored = int(row[0]) if row else 0
                start = max(stored, self._legacy_counter(), self._highest_am_number()) + 1
                end = start + count - 1
                connection.execute(
                    "INSERT INTO am_counter (id, value) VALUES (1, ?) "
                    "ON CONFLICT(id) DO UPDATE SET value = excluded.value",
                    (end,),
                )
                connection.execute("COMMIT")
                write_text(self.root / ".am-counter", f"{end}\n")
                return list(range(start, end + 1))
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

    def _legacy_counter(self) -> int:
        try:
            return int((self.root / ".am-counter").read_text(encoding="utf-8").strip())
        except (FileNotFoundError, ValueError, OSError):
            return 0

    def _counter_value(self) -> int:
        database = self.root / ".am-ids.sqlite3"
        if not database.is_file():
            return self._legacy_counter()
        try:
            connection = sqlite3.connect(database, timeout=30.0)
            row = connection.execute(
                "SELECT value FROM am_counter WHERE id = 1"
            ).fetchone()
            connection.close()
        except sqlite3.Error:
            return self._legacy_counter()
        return int(row[0]) if row else self._legacy_counter()

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
        visible = [path for path in matches if self._brief_is_published(path, am_id)]
        return (am_id, visible[0]) if visible else None

    def _brief_is_published(self, path: Path, am_id: str) -> bool:
        """Hide briefs whose source run did not complete publication."""
        try:
            match = _BRIEF_SOURCE_RE.search(path.read_text(encoding="utf-8"))
            if match is None:
                return False
            source_run = json.loads(match.group(1))
            if not isinstance(source_run, str) or not _RUN_ID_RE.fullmatch(source_run):
                return False
            manifest = self.runs_dir / source_run / "run.json"
            if not manifest.is_file():
                return False
            data = read_json(manifest)
        except (OSError, ValueError):
            return False
        return (
            isinstance(data, dict)
            and data.get("status") == "completed"
            and data.get("publication_status") == "complete"
            and am_id in data.get("opportunities", [])
        )

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


@contextmanager
def _legacy_counter_lock(root: Path):
    """Coordinate with the pre-SQLite POSIX allocator during migration."""
    lock_path = root / ".am-id.lock"
    try:
        import fcntl
    except ImportError:
        # SQLite remains the portable allocator on platforms without fcntl.
        yield
        return
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


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
