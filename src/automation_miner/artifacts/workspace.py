"""Workspace layout: run directories, JSON artifacts, global AM numbering.

Layout (per DESIGN.md / spec 03):
    <workspace>/registry.json
    <workspace>/runs/<YYYY-MM-DD>_<domain-slug>/...
    <workspace>/opps/<domain-slug>/AM-XXX-<slug>.md
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

_AM_RE = re.compile(r"AM-(\d+)")


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

    def ensure(self) -> None:
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.opps_dir.mkdir(parents=True, exist_ok=True)

    def new_run_dir(self, domain_slug: str) -> Path:
        """Create runs/YYYY-MM-DD_<slug> (suffix -2, -3... if repeated today)."""
        self.ensure()
        base = f"{datetime.now():%Y-%m-%d}_{domain_slug}"
        run_dir = self.runs_dir / base
        n = 2
        while run_dir.exists():
            run_dir = self.runs_dir / f"{base}-{n}"
            n += 1
        (run_dir / "layers").mkdir(parents=True)
        (run_dir / "drafts").mkdir()
        return run_dir

    def opp_dir(self, domain_slug: str) -> Path:
        path = self.opps_dir / domain_slug
        path.mkdir(parents=True, exist_ok=True)
        return path

    def next_am_number(self) -> int:
        """Global sequential numbering: max existing AM id + 1 (start at 1)."""
        highest = 0
        if self.opps_dir.exists():
            for f in self.opps_dir.rglob("AM-*.md"):
                m = _AM_RE.match(f.name)
                if m:
                    highest = max(highest, int(m.group(1)))
        return highest + 1

    def list_runs(self) -> list[str]:
        if not self.runs_dir.exists():
            return []
        return sorted(p.name for p in self.runs_dir.iterdir() if p.is_dir())


def write_json(path: Path, payload: BaseModel | dict[str, Any] | list[Any]) -> None:
    """Persist a JSON artifact (pydantic model or plain data)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, BaseModel):
        text = payload.model_dump_json(indent=2)
    else:
        text = json.dumps(payload, indent=2, ensure_ascii=False, default=str)
    path.write_text(text + "\n", encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))
