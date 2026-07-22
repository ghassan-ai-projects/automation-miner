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
DIGEST_CHUNK_CHARS = 12_000
MAX_DOMAIN_CHARS = 200
MAX_SLUG_CHARS = 80
SUPPORTED_SUFFIXES = {".md", ".txt", ".json", ".yaml", ".yml"}


def slugify(text: str) -> str:
    """Domain slug: lowercase, hyphens for spaces, special chars removed."""
    text = re.sub(r"\(.*?\)", "", text.lower())
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")[:MAX_SLUG_CHARS].rstrip("-") or "domain"


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
    domain = " ".join(domain.split()).strip()[:MAX_DOMAIN_CHARS] or "untitled-domain"
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
    content = idea.strip()
    if not content:
        raise ValueError("Idea input must not be empty")
    domain = content.splitlines()[0].strip()
    return _packet(domain, content, "idea", constraints)


def ingest_file(path: Path, constraints: str = "") -> ContextPacket:
    """Read one md/txt/json/yaml file as context."""
    if not path.is_file():
        raise ValueError(f"Input file does not exist or is not a file: {path}")
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
    if not folder.is_dir():
        raise ValueError(f"Knowledge-base folder does not exist or is not a directory: {folder}")
    files = sorted(
        p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES
    )
    if not files:
        raise ValueError(f"No supported files (.md/.txt/.json/.yaml) found in {folder}")

    documents = [(f, _read_file(f)) for f in files]
    parts = [f"=== {f.name} ===\n{text}" for f, text in documents]
    content = "\n\n".join(parts)

    digested = False
    if len(content) > TOKEN_BUDGET_CHARS and model is not None:
        content = _digest_documents(documents, model)
        digested = True

    return _packet(
        folder.name,
        content,
        "kb",
        constraints,
        files=[str(f) for f in files],
        digested=digested,
    )


def _digest_documents(documents: list[tuple[Path, str]], model: MinerModel) -> str:
    """Map bounded chunks, then hierarchically reduce digests to the context budget."""
    digests: list[str] = []
    for path, content in documents:
        chunks = [
            content[offset : offset + DIGEST_CHUNK_CHARS]
            for offset in range(0, len(content), DIGEST_CHUNK_CHARS)
        ] or [""]
        for index, chunk in enumerate(chunks, 1):
            label = path.name if len(chunks) == 1 else f"{path.name} (part {index}/{len(chunks)})"
            digest = model.chat("mapper", "", digest_prompt(label, chunk))
            digests.append(f"=== {label} ===\n{digest}")

    content = "\n\n".join(digests)
    round_no = 1
    while len(content) > TOKEN_BUDGET_CHARS:
        reduced = []
        for offset in range(0, len(content), DIGEST_CHUNK_CHARS):
            chunk = content[offset : offset + DIGEST_CHUNK_CHARS]
            label = f"digest reduction {round_no}.{len(reduced) + 1}"
            reduced.append(model.chat("mapper", "", digest_prompt(label, chunk)))
        candidate = "\n\n".join(reduced)
        if len(candidate) >= len(content):
            break
        content = candidate
        round_no += 1
    return content
