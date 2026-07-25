"""Reader discovery and dispatch.

Three ways to add a format, in increasing priority — none of them require
editing this package:

1. **Built-ins** shipped here (priority 0).
2. **Entry points** in the ``automation_miner.readers`` group (priority 10).
   Any installed distribution can contribute one::

       [project.entry-points."automation_miner.readers"]
       rtf = "my_pkg.readers:RtfReader"

3. **``miner.toml`` declarations** (priority 20) — no packaging at all::

       [readers]
       disabled = ["pptx"]
       max_file_bytes = 20_000_000

       [readers.csv]
       sample_rows = 40

       [[readers.custom]]
       suffixes = [".rtf"]
       factory = "my_pkg.readers:RtfReader"

A plugin that fails to import is recorded in :attr:`ReaderRegistry.errors` and
reported — it never prevents a run from starting. Files whose suffix has no
registered reader fall back to text extraction when they are not binary, so an
unanticipated ``.sql`` or ``.ini`` in a knowledge base still contributes
evidence instead of vanishing.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from automation_miner.readers.base import (
    Availability,
    MediaType,
    Reader,
    ReaderError,
    SourceDocument,
)
from automation_miner.readers.documents import DocxReader, PdfReader, PptxReader
from automation_miner.readers.encoding import looks_binary
from automation_miner.readers.structured import JsonReader, YamlReader
from automation_miner.readers.tabular import CsvReader, XlsxReader
from automation_miner.readers.text import HtmlReader, TextReader

ENTRY_POINT_GROUP = "automation_miner.readers"
DEFAULT_MAX_FILE_BYTES = 20_000_000

# Keys under [readers] that configure the registry rather than a single reader.
_RESERVED = {"disabled", "enabled", "custom", "max_file_bytes", "fallback_text", "encoding"}

# Suffixes that must never reach the plain-text fallback: extracting their
# container bytes as prose yields noise, not evidence. A byte sniff catches most
# of these, but not reliably — an uncompressed PDF looks textual in its header.
NEVER_TEXT: frozenset[str] = frozenset(
    {
        ".pdf", ".doc", ".docx", ".dot", ".dotx", ".odt",
        ".xls", ".xlsx", ".xlsm", ".xlsb", ".ods",
        ".ppt", ".pptx", ".odp", ".key", ".pages", ".numbers",
        ".zip", ".gz", ".bz2", ".xz", ".tar", ".7z", ".rar", ".jar",
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp",
        ".ico", ".svgz", ".psd", ".ai", ".eps",
        ".mp3", ".mp4", ".m4a", ".mov", ".avi", ".mkv", ".wav", ".flac", ".ogg",
        ".exe", ".dll", ".so", ".dylib", ".bin", ".dmg", ".pkg", ".deb", ".rpm",
        ".db", ".sqlite", ".sqlite3", ".mdb", ".accdb", ".parquet", ".avro", ".pyc",
        ".woff", ".woff2", ".ttf", ".otf",
    }
)

# Suffixes an optional built-in reader would handle — used to turn "unsupported"
# into an actionable install hint.
_EXTRA_FOR_SUFFIX: dict[str, str] = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".xlsx": "xlsx",
    ".xlsm": "xlsx",
    ".pptx": "pptx",
}

BUILTIN_READERS: tuple[type, ...] = (
    TextReader,
    JsonReader,
    YamlReader,
    CsvReader,
    HtmlReader,
    PdfReader,
    DocxReader,
    XlsxReader,
    PptxReader,
)


@dataclass(frozen=True)
class ReaderInfo:
    """One row of ``automation-miner readers`` output."""

    name: str
    suffixes: tuple[str, ...]
    media_type: str
    available: bool
    reason: str
    source: str


@dataclass(frozen=True)
class Registration:
    reader: Reader
    priority: int
    source: str


@dataclass
class ReaderRegistry:
    """Suffix → reader dispatch with plugin discovery."""

    registrations: dict[str, Registration] = field(default_factory=dict)
    by_suffix: dict[str, Registration] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES
    fallback_text: bool = True

    def register(self, reader: Reader, priority: int = 0, source: str = "builtin") -> None:
        """Add a reader, claiming its suffixes unless a higher priority holds them."""
        problem = _validate(reader)
        if problem:
            self.errors.append(f"{source}: {problem}")
            return
        registration = Registration(reader=reader, priority=priority, source=source)
        self.registrations[reader.name] = registration
        for suffix in reader.suffixes:
            key = suffix.lower()
            existing = self.by_suffix.get(key)
            if existing is None or priority >= existing.priority:
                self.by_suffix[key] = registration

    def unregister(self, name: str) -> None:
        """Remove a reader by name and release the suffixes it claimed."""
        registration = self.registrations.pop(name, None)
        if registration is None:
            return
        for suffix, held in list(self.by_suffix.items()):
            if held is registration:
                del self.by_suffix[suffix]

    @property
    def suffixes(self) -> tuple[str, ...]:
        return tuple(sorted(self.by_suffix))

    def reader_for(self, path: Path) -> Reader | None:
        registration = self.by_suffix.get(path.suffix.lower())
        return registration.reader if registration else None

    def handles(self, path: Path) -> bool:
        return path.suffix.lower() in self.by_suffix

    def read(self, path: Path) -> SourceDocument:
        """Extract one file. Raises :class:`ReaderError` with an actionable reason."""
        try:
            size = path.stat().st_size
        except OSError as exc:
            raise ReaderError(f"cannot stat file: {exc}") from exc
        if size == 0:
            raise ReaderError("file is empty")
        if size > self.max_file_bytes:
            raise ReaderError(
                f"file is {size:,} bytes, over the {self.max_file_bytes:,} byte limit "
                "(raise readers.max_file_bytes to include it)"
            )

        reader = self.reader_for(path)
        fallback_note = ""
        if reader is None:
            suffix = path.suffix.lower()
            label = suffix or "extensionless"
            if extra := _EXTRA_FOR_SUFFIX.get(suffix):
                raise ReaderError(
                    f"no reader for {label} files — enable it with: uv sync --extra {extra}"
                )
            if suffix in NEVER_TEXT:
                raise ReaderError(f"no reader for {label} files (binary format)")
            if not self.fallback_text:
                raise ReaderError(f"no reader registered for {label} files")
            try:
                with path.open("rb") as handle:
                    head = handle.read(4096)
            except OSError as exc:
                raise ReaderError(f"cannot read file: {exc}") from exc
            if looks_binary(head):
                raise ReaderError(f"no reader for {label} files and the content is binary")
            reader = self.registrations["text"].reader
            fallback_note = f"no reader for {label}; read as text"

        availability = reader.available()
        if not availability.ok:
            raise ReaderError(f"{reader.name} reader unavailable: {availability.reason}")

        document = reader.read(path)
        if fallback_note:
            document.meta["fallback"] = fallback_note
        return document

    def describe(self) -> list[ReaderInfo]:
        """Every registered reader with live availability — powers the CLI listing."""
        rows: list[ReaderInfo] = []
        for name, registration in sorted(self.registrations.items()):
            reader = registration.reader
            availability = reader.available()
            claimed = tuple(
                s for s in reader.suffixes if self.by_suffix.get(s.lower()) is registration
            )
            rows.append(
                ReaderInfo(
                    name=name,
                    suffixes=claimed or reader.suffixes,
                    media_type=str(getattr(reader, "media_type", MediaType.TEXT)),
                    available=availability.ok,
                    reason=availability.reason,
                    source=registration.source,
                )
            )
        return rows


def _validate(reader: object) -> str:
    """Return a problem description, or empty string when the reader is usable."""
    name = getattr(reader, "name", None)
    if not isinstance(name, str) or not name:
        return f"{reader!r} has no usable 'name' attribute"
    suffixes = getattr(reader, "suffixes", None)
    if not isinstance(suffixes, (tuple, list)) or not suffixes:
        return f"reader {name!r} declares no suffixes"
    if not all(isinstance(s, str) and s.startswith(".") for s in suffixes):
        return f"reader {name!r} has suffixes that are not dot-prefixed strings"
    if not callable(getattr(reader, "read", None)):
        return f"reader {name!r} has no callable read()"
    if not callable(getattr(reader, "available", None)):
        return f"reader {name!r} has no callable available()"
    return ""


def _load_factory(target: str) -> Any:
    """Import ``module:attr`` or ``module.attr`` and return the object."""
    if ":" in target:
        module_name, _, attribute = target.partition(":")
    else:
        module_name, _, attribute = target.rpartition(".")
    if not module_name or not attribute:
        raise ImportError(f"{target!r} is not a module:attribute path")
    module = importlib.import_module(module_name)
    try:
        return getattr(module, attribute)
    except AttributeError as exc:
        raise ImportError(f"{module_name!r} has no attribute {attribute!r}") from exc


def _instantiate(factory: Any, options: dict[str, Any]) -> Reader:
    """Build a reader from a class or zero-argument callable."""
    if isinstance(factory, type):
        try:
            return factory(**options)  # type: ignore[return-value]
        except TypeError:
            return factory()  # type: ignore[return-value]
    if callable(factory):
        return factory()  # type: ignore[return-value]
    return factory  # already an instance


def build_registry(config: dict[str, Any] | None = None) -> ReaderRegistry:
    """Assemble the effective registry: built-ins, entry points, then config."""
    settings = dict(config or {})
    disabled = {str(n).lower() for n in settings.get("disabled", []) or []}
    enabled = settings.get("enabled")
    allow = {str(n).lower() for n in enabled} if enabled else None

    registry = ReaderRegistry(
        max_file_bytes=int(settings.get("max_file_bytes", DEFAULT_MAX_FILE_BYTES)),
        fallback_text=bool(settings.get("fallback_text", True)),
    )
    # A workspace-wide encoding override applies to every reader that decodes text.
    shared: dict[str, Any] = {}
    if encoding := str(settings.get("encoding", "") or ""):
        shared["encoding"] = encoding
    per_reader = {
        key: {**shared, **value}
        for key, value in settings.items()
        if key not in _RESERVED and isinstance(value, dict)
    }

    def wanted(name: str) -> bool:
        lowered = name.lower()
        return lowered not in disabled and (allow is None or lowered in allow)

    for cls in BUILTIN_READERS:
        name = getattr(cls, "name", cls.__name__)
        if wanted(name):
            options = per_reader.get(name, dict(shared))
            registry.register(cls(**options), priority=0, source="builtin")

    for name, reader, error in _discover_entry_points():
        if error:
            registry.errors.append(error)
        elif reader is not None and wanted(name):
            registry.register(reader, priority=10, source="entry-point")

    for index, entry in enumerate(settings.get("custom", []) or [], 1):
        if not isinstance(entry, dict):
            registry.errors.append(f"readers.custom[{index}] is not a table")
            continue
        target = str(entry.get("factory", "")).strip()
        if not target:
            registry.errors.append(f"readers.custom[{index}] has no 'factory'")
            continue
        try:
            factory = _load_factory(target)
            options = {
                k: v for k, v in entry.items() if k not in {"factory", "suffixes", "name"}
            }
            reader = _instantiate(factory, options)
        except Exception as exc:
            registry.errors.append(f"readers.custom[{index}] {target!r} failed to load: {exc}")
            continue
        if suffixes := entry.get("suffixes"):
            reader.suffixes = tuple(str(s).lower() for s in suffixes)  # type: ignore[misc]
        if name := entry.get("name"):
            reader.name = str(name)  # type: ignore[misc]
        if wanted(getattr(reader, "name", "")):
            registry.register(reader, priority=20, source="miner.toml")

    # The text reader backs the non-binary fallback path, so it must always exist.
    if "text" not in registry.registrations:
        registry.register(TextReader(), priority=-1, source="builtin (fallback)")
    return registry


def _discover_entry_points() -> list[tuple[str, Reader | None, str]]:
    """Load third-party readers, converting failures into reportable errors."""
    from importlib.metadata import entry_points

    found: list[tuple[str, Reader | None, str]] = []
    try:
        points = entry_points(group=ENTRY_POINT_GROUP)
    except Exception as exc:
        return [("", None, f"entry-point discovery failed: {exc}")]
    for point in points:
        try:
            reader = _instantiate(point.load(), {})
        except Exception as exc:
            found.append((point.name, None, f"entry-point {point.name!r} failed to load: {exc}"))
            continue
        found.append((getattr(reader, "name", point.name), reader, ""))
    return found


__all__ = [
    "BUILTIN_READERS",
    "ENTRY_POINT_GROUP",
    "Availability",
    "ReaderError",
    "ReaderInfo",
    "ReaderRegistry",
    "build_registry",
]
