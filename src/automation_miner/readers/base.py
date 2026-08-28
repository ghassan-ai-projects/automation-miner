"""Reader plugin contract: how one source file becomes evidence segments.

A reader turns a file into a :class:`SourceDocument` — an ordered list of
:class:`Segment`s, each carrying a human-readable ``locator`` (``"p.4"``,
``"Sheet1!rows 200-260"``, ``"## Claims > ### Rework"``). Locators are the
provenance the rest of the pipeline cites, so a groundedness check can point at
a real location in the user's own documents instead of an opaque blob offset.

Readers are plugins: supporting a new format needs **no change to this
package**. Ship an ``automation_miner.readers`` entry point, or name a factory
in ``miner.toml``. See :mod:`automation_miner.readers.registry`.

Writing a reader is intentionally small — subclass :class:`BaseReader`, declare
``name``/``suffixes``, implement ``parse``:

    class RtfReader(BaseReader):
        name = "rtf"
        suffixes = (".rtf",)
        media_type = MediaType.DOCUMENT

        def parse(self, path, data):
            return [Segment(text=striprtf.rtf_to_text(self.decode(data)))]
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import Field

from automation_miner.readers.encoding import decode_bytes
from automation_miner.schemas import ArtifactModel


class MediaType(StrEnum):
    """What kind of evidence a document holds — drives chunking strategy."""

    TEXT = "text"
    MARKUP = "markup"
    STRUCTURED = "structured"
    TABULAR = "tabular"
    DOCUMENT = "document"
    PRESENTATION = "presentation"


class Segment(ArtifactModel):
    """One addressable piece of a source document."""

    text: str
    locator: str = ""

    @property
    def chars(self) -> int:
        return len(self.text)


class SourceDocument(ArtifactModel):
    """Extraction result for one file."""

    path: str
    reader: str
    media_type: MediaType
    segments: list[Segment] = Field(default_factory=list)
    encoding: str = ""
    meta: dict[str, str | int | float | bool] = Field(default_factory=dict)

    @property
    def name(self) -> str:
        return Path(self.path).name

    @property
    def chars(self) -> int:
        return sum(s.chars for s in self.segments)

    def text(self, separator: str = "\n\n") -> str:
        """Flatten segments back into one string (locators dropped)."""
        return separator.join(s.text for s in self.segments if s.text)


class ReaderError(Exception):
    """A reader could not extract this file. Caught per-file, never fatal."""

    def __init__(
        self,
        message: str,
        *,
        meta: dict[str, str | int | float | bool] | None = None,
    ) -> None:
        super().__init__(message)
        self.meta = meta or {}


@dataclass(frozen=True)
class Availability:
    """Whether a registered reader can actually run right now."""

    ok: bool
    reason: str = ""

    @classmethod
    def yes(cls) -> Availability:
        return cls(True)

    @classmethod
    def no(cls, reason: str) -> Availability:
        return cls(False, reason)


@runtime_checkable
class Reader(Protocol):
    """The full contract a plugin must satisfy."""

    name: str
    suffixes: tuple[str, ...]
    media_type: MediaType

    def available(self) -> Availability:
        """Report whether optional dependencies are importable."""
        ...

    def read(self, path: Path) -> SourceDocument:
        """Extract one file, or raise :class:`ReaderError`."""
        ...


def missing_dependency(module: str, extra: str) -> Availability:
    """Availability for an optional parser dependency, with an actionable fix."""
    try:
        __import__(module)
    except ImportError:
        return Availability.no(
            f"{module!r} is not installed — run: uv sync --extra {extra}"
        )
    return Availability.yes()


class BaseReader:
    """Convenience base: byte loading, decoding, and the SourceDocument wrapper.

    Subclasses implement :meth:`parse` and get error isolation for free.
    """

    name: str = "base"
    suffixes: tuple[str, ...] = ()
    media_type: MediaType = MediaType.TEXT
    binary: bool = False

    def __init__(self, **options: object) -> None:
        self.options = options

    def available(self) -> Availability:
        return Availability.yes()

    def parse(self, path: Path, data: bytes) -> list[Segment]:
        raise NotImplementedError

    def decode(self, data: bytes) -> str:
        preferred = str(self.options.get("encoding", "") or "")
        text, self._encoding = decode_bytes(data, preferred)
        return text

    def read(self, path: Path) -> SourceDocument:
        self._encoding = ""
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise ReaderError(f"cannot read file: {exc}") from exc
        segments = [s for s in self.parse(path, data) if s.text.strip()]
        return SourceDocument(
            path=str(path),
            reader=self.name,
            media_type=self.media_type,
            segments=segments,
            encoding="" if self.binary else self._encoding,
            meta=self.meta(path, data, segments),
        )

    def meta(
        self, path: Path, data: bytes, segments: list[Segment]
    ) -> dict[str, str | int | float | bool]:
        return {"bytes": len(data), "segments": len(segments)}

    def option(self, key: str, default: int) -> int:
        """Read an int option supplied via ``[readers.<name>]`` in miner.toml."""
        value = self.options.get(key, default)
        try:
            return int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return default
