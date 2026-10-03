"""Reader discovery: built-ins, entry-point plugins, and miner.toml factories."""

from __future__ import annotations

import importlib
from typing import Any, cast

from automation_miner.readers.base import Reader
from automation_miner.readers.text import TextReader
from automation_miner.readers.registry import (
    BUILTIN_READERS,
    DEFAULT_MAX_FILE_BYTES,
    ENTRY_POINT_GROUP,
    ReaderRegistry,
    _RESERVED,
)


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
            return cast(Reader, factory(**options))
        except TypeError:
            return cast(Reader, factory())
    if callable(factory):
        return cast(Reader, factory())
    return cast(Reader, factory)  # already an instance


class _Selection:
    """Which readers the [readers] table enables, and the options each one gets."""

    def __init__(self, settings: dict[str, Any]) -> None:
        self.disabled = {str(n).lower() for n in settings.get("disabled", []) or []}
        enabled = settings.get("enabled")
        self.allow = {str(n).lower() for n in enabled} if enabled else None
        # A workspace-wide encoding override applies to every reader that decodes text.
        self.shared: dict[str, Any] = {}
        if encoding := str(settings.get("encoding", "") or ""):
            self.shared["encoding"] = encoding
        self.per_reader = {
            key: {**self.shared, **value}
            for key, value in settings.items()
            if key not in _RESERVED and isinstance(value, dict)
        }

    def wanted(self, name: str) -> bool:
        lowered = name.lower()
        return lowered not in self.disabled and (self.allow is None or lowered in self.allow)

    def options(self, name: str) -> dict[str, Any]:
        return self.per_reader.get(name, dict(self.shared))


def _custom_reader(index: int, entry: object) -> Reader:
    """Build one ``[[readers.custom]]`` reader; ValueError carries the reportable reason."""
    if not isinstance(entry, dict):
        raise ValueError(f"readers.custom[{index}] is not a table")
    target = str(entry.get("factory", "")).strip()
    if not target:
        raise ValueError(f"readers.custom[{index}] has no 'factory'")
    try:
        options = {k: v for k, v in entry.items() if k not in {"factory", "suffixes", "name"}}
        reader = _instantiate(_load_factory(target), options)
    except Exception as exc:
        raise ValueError(f"readers.custom[{index}] {target!r} failed to load: {exc}") from exc
    if suffixes := entry.get("suffixes"):
        reader.suffixes = tuple(str(s).lower() for s in suffixes)
    if name := entry.get("name"):
        reader.name = str(name)
    return reader


def _register_custom(registry: ReaderRegistry, entries: list[Any], selection: _Selection) -> None:
    for index, entry in enumerate(entries, 1):
        try:
            reader = _custom_reader(index, entry)
        except ValueError as exc:
            registry.errors.append(str(exc))
            continue
        if selection.wanted(getattr(reader, "name", "")):
            registry.register(reader, priority=20, source="miner.toml")


def build_registry(config: dict[str, Any] | None = None) -> ReaderRegistry:
    """Assemble the effective registry: built-ins, entry points, then config."""
    settings = dict(config or {})
    selection = _Selection(settings)
    registry = ReaderRegistry(
        max_file_bytes=int(settings.get("max_file_bytes", DEFAULT_MAX_FILE_BYTES)),
        fallback_text=bool(settings.get("fallback_text", True)),
    )
    for cls in BUILTIN_READERS:
        name = getattr(cls, "name", cls.__name__)
        if selection.wanted(name):
            registry.register(cls(**selection.options(name)), priority=0, source="builtin")
    for name, reader, error in _discover_entry_points():
        if error:
            registry.errors.append(error)
        elif reader is not None and selection.wanted(name):
            registry.register(reader, priority=10, source="entry-point")
    _register_custom(registry, settings.get("custom", []) or [], selection)
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


__all__ = ["build_registry"]
