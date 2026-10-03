"""Input normalization: idea string, file, or KB folder → ContextPacket.

Every input becomes a numbered evidence index (a :class:`Chunk` list) plus a
budget-bounded ``overview`` used for domain mapping. Downstream stages select
the chunks relevant to their own question instead of receiving one shared blob.

Failure handling is per-file. A malformed ``.json``, a password-protected PDF, a
file over the size cap, or a format with no available reader is recorded in
``skipped`` with a reason and the run continues — previously any one of those
aborted ingestion of the entire folder.

Oversized single files are digested like knowledge bases rather than hard-cut:
a 220k-char brief used to be truncated mid-sentence to 18% of its content with
nothing but a boolean to show for it.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Callable

from automation_miner.context import ContextBudget, estimate_tokens
from automation_miner.readers import (
    MediaType,
    ReaderError,
    ReaderRegistry,
    Segment,
    SourceDocument,
    build_registry,
)
from automation_miner.schemas import ContextPacket, InputQuality, SkippedFile

from automation_miner.ingest.packet import (
    MAX_DOMAIN_CHARS,
    MAX_SLUG_CHARS,
    PacketSource,
    build_packet,
    clean_domain,
    slugify,
)

if TYPE_CHECKING:
    from automation_miner.models.client import MinerModel, RunScopedModel

# Bound on how much of a tree one run will walk, so a symlink loop or an
# accidentally huge folder fails loudly instead of hanging.
MAX_KB_FILES = 5_000


def _walk_problem(path: Path, root: Path) -> str:
    """Why a walked path is skipped ("" to keep it)."""
    try:
        resolved = path.resolve()
    except OSError as exc:
        return f"cannot resolve path: {exc}"
    if not resolved.is_relative_to(root):
        return "symlink points outside the knowledge base"
    return ""


def _enumerate_files(folder: Path) -> tuple[list[Path], list[SkippedFile]]:
    """List candidate files, refusing to follow directory symlinks out of the tree."""
    files: list[Path] = []
    skipped: list[SkippedFile] = []
    root = folder.resolve()
    for path in sorted(folder.rglob("*")):
        if len(files) >= MAX_KB_FILES:
            reason = f"knowledge base exceeds the {MAX_KB_FILES} file limit"
            skipped.append(SkippedFile(path=str(path), reason=reason))
            break
        if path.is_dir():
            continue
        problem = _walk_problem(path, root)
        if problem:
            skipped.append(SkippedFile(path=str(path), reason=problem))
        elif path.is_file():
            files.append(path)
    return files, skipped


def _read_one(path: Path, registry: ReaderRegistry) -> SourceDocument | SkippedFile:
    """The extracted document, or why the file was skipped."""
    try:
        document = registry.read(path)
    except ReaderError as exc:
        reader = registry.reader_for(path)
        reason = str(exc)
        if exc.meta.get("page_errors"):
            reason += f"; page telemetry: {exc.meta['page_errors']}"
        return SkippedFile(path=str(path), reason=reason, reader=getattr(reader, "name", ""))
    except Exception as exc:  # a plugin reader may raise anything
        return SkippedFile(path=str(path), reason=f"{type(exc).__name__}: {exc}")
    if not document.segments:
        return SkippedFile(path=str(path), reason="no text extracted", reader=document.reader)
    return document


def _read_all(
    paths: list[Path], registry: ReaderRegistry
) -> tuple[list[SourceDocument], list[SkippedFile]]:
    """Extract every file, isolating failures so one bad file cannot end the run."""
    results = [_read_one(path, registry) for path in paths]
    documents = [r for r in results if isinstance(r, SourceDocument)]
    return documents, [r for r in results if isinstance(r, SkippedFile)]


def ingest_idea(
    idea: str, constraints: str = "", budget: ContextBudget | None = None,
    preflight_callback: Callable[[InputQuality], None] | None = None,
) -> ContextPacket:
    """Use a raw idea/domain string directly as context."""
    content = idea.strip()
    if not content:
        raise ValueError("Idea input must not be empty")
    document = SourceDocument(
        path="<idea>", reader="idea", media_type=MediaType.TEXT, segments=[Segment(text=content)]
    )
    packet = build_packet(
        PacketSource(
            domain=content.splitlines()[0], source_kind="idea", documents=[document],
            constraints=constraints, budget=budget or ContextBudget(),
            preflight_callback=preflight_callback,
        )
    )
    return packet.model_copy(update={"files": []})


def ingest_file(
    path: Path, constraints: str = "", model: MinerModel | RunScopedModel | None = None,
    budget: ContextBudget | None = None, registry: ReaderRegistry | None = None,
    cache_root: Path | None = None,
    preflight_callback: Callable[[InputQuality], None] | None = None,
) -> ContextPacket:
    """Read one file of any registered format as context."""
    if not path.is_file():
        raise ValueError(f"Input file does not exist or is not a file: {path}")
    registry = registry or build_registry()
    try:
        document = registry.read(path)
    except ReaderError as exc:
        raise ValueError(f"Cannot read {path}: {exc}") from exc
    if not document.segments:
        raise ValueError(f"No text could be extracted from {path}")
    return build_packet(
        PacketSource(
            domain=path.stem, source_kind="file", documents=[document], constraints=constraints,
            budget=budget or ContextBudget(), model=model, cache_root=cache_root,
            reader_errors=list(registry.errors), preflight_callback=preflight_callback,
        )
    )


def ingest_kb(
    folder: Path, constraints: str = "", model: MinerModel | RunScopedModel | None = None,
    budget: ContextBudget | None = None, registry: ReaderRegistry | None = None,
    cache_root: Path | None = None,
    preflight_callback: Callable[[InputQuality], None] | None = None,
) -> ContextPacket:
    """Normalize a knowledge-base folder into one bounded evidence index."""
    if not folder.is_dir():
        raise ValueError(f"Knowledge-base folder does not exist or is not a directory: {folder}")
    registry = registry or build_registry()
    candidates, walk_skips = _enumerate_files(folder)
    if not candidates:
        raise ValueError(f"No files found in {folder}")
    documents, read_skips = _read_all(candidates, registry)
    skipped = walk_skips + read_skips
    if not documents:
        reasons = "; ".join(f"{Path(s.path).name}: {s.reason}" for s in skipped[:5])
        raise ValueError(f"No readable files in {folder}. Skipped: {reasons}")
    return build_packet(
        PacketSource(
            domain=folder.name, source_kind="kb", documents=documents, constraints=constraints,
            budget=budget or ContextBudget(), skipped=skipped, model=model, cache_root=cache_root,
            reader_errors=list(registry.errors), preflight_callback=preflight_callback,
        )
    )


def evidence_tokens(packet: ContextPacket) -> int:
    """Token size of a packet's evidence index."""
    return sum(estimate_tokens(chunk.text) for chunk in packet.chunks)


__all__ = [
    "MAX_DOMAIN_CHARS",
    "MAX_KB_FILES",
    "MAX_SLUG_CHARS",
    "clean_domain",
    "evidence_tokens",
    "ingest_file",
    "ingest_idea",
    "ingest_kb",
    "slugify",
]
