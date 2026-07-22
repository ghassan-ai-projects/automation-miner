"""Input normalization: idea string, file, or KB folder -> ContextPacket.

Everything is bounded by a ~40k character budget. Oversized KB folders are
digested per-file via the mapper role (map-reduce), then merged.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from automation_miner.prompts import digest_prompt
from automation_miner.schemas import ContextPacket

if TYPE_CHECKING:
    from automation_miner.models.client import MinerModel

TOKEN_BUDGET_CHARS = 40_000
SUPPORTED_SUFFIXES = {".md", ".txt", ".json", ".yaml", ".yml"}


def slugify(text: str) -> str:
    """Domain slug: lowercase, hyphens for spaces, special chars removed."""
    text = re.sub(r"\(.*?\)", "", text.lower())
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-") or "domain"


def _read_file(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        return json.dumps(json.loads(text), indent=2)
    if path.suffix in {".yaml", ".yml"}:
        return json.dumps(yaml.safe_load(text), indent=2, default=str)
    return text


def _packet(
    domain: str,
    content: str,
    source_kind: str,
    constraints: str,
    files: list[str] | None = None,
    digested: bool = False,
) -> ContextPacket:
    truncated = False
    if len(content) > TOKEN_BUDGET_CHARS:
        content = content[:TOKEN_BUDGET_CHARS] + "\n\n[... truncated to fit context budget ...]"
        truncated = True
    return ContextPacket(
        domain=domain,
        domain_slug=slugify(domain),
        constraints=constraints,
        source_kind=source_kind,  # type: ignore[arg-type]
        content=content,
        files=files or [],
        digested=digested,
        truncated=truncated,
    )


def ingest_idea(idea: str, constraints: str = "") -> ContextPacket:
    """Use a raw idea/domain string directly as context."""
    domain = idea.strip().splitlines()[0].strip() or "untitled-domain"
    return _packet(domain, idea.strip(), "idea", constraints)


def ingest_file(path: Path, constraints: str = "") -> ContextPacket:
    """Read one md/txt/json/yaml file as context."""
    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise ValueError(f"Unsupported file type: {path.suffix}")
    content = _read_file(path)
    return _packet(path.stem, content, "file", constraints, files=[str(path)])


def ingest_kb(folder: Path, constraints: str = "", model: MinerModel | None = None) -> ContextPacket:
    """Normalize a knowledge-base folder into one bounded context packet.

    Files are enumerated sorted. If the concatenation exceeds the budget and a
    model is available, each file is digested via the mapper role (map), then
    the digests are merged (reduce) and budget-truncated.
    """
    files = sorted(
        p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES
    )
    if not files:
        raise ValueError(f"No supported files (.md/.txt/.json/.yaml) found in {folder}")

    parts: list[str] = []
    for f in files:
        parts.append(f"=== {f.name} ===\n{_read_file(f)}")
    content = "\n\n".join(parts)

    digested = False
    if len(content) > TOKEN_BUDGET_CHARS and model is not None:
        digests = [
            f"=== {f.name} ===\n{model.chat('mapper', '', digest_prompt(f.name, _read_file(f)))}"
            for f in files
        ]
        content = "\n\n".join(digests)
        digested = True

    return _packet(
        folder.name,
        content,
        "kb",
        constraints,
        files=[str(f) for f in files],
        digested=digested,
    )
