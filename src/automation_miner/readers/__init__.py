"""Pluggable document readers.

``build_registry(config)`` returns the effective suffix → reader mapping,
assembled from built-ins, ``automation_miner.readers`` entry points, and
``[readers]`` in ``miner.toml``. See :mod:`automation_miner.readers.registry`
for how to add a format without changing this package, and
:mod:`automation_miner.readers.base` for the reader contract.
"""

from __future__ import annotations

from automation_miner.readers.base import (
    Availability,
    BaseReader,
    MediaType,
    Reader,
    ReaderError,
    Segment,
    SkippedFile,
    SourceDocument,
    missing_dependency,
)
from automation_miner.readers.documents import DocxReader, PdfReader, PptxReader
from automation_miner.readers.encoding import decode_bytes, looks_binary
from automation_miner.readers.registry import (
    BUILTIN_READERS,
    ENTRY_POINT_GROUP,
    DEFAULT_MAX_FILE_BYTES,
    ReaderInfo,
    ReaderRegistry,
    build_registry,
)
from automation_miner.readers.structured import JsonReader, YamlReader
from automation_miner.readers.tabular import CsvReader, XlsxReader
from automation_miner.readers.text import HtmlReader, TextReader, split_markdown

__all__ = [
    "BUILTIN_READERS",
    "DEFAULT_MAX_FILE_BYTES",
    "ENTRY_POINT_GROUP",
    "Availability",
    "BaseReader",
    "CsvReader",
    "DocxReader",
    "HtmlReader",
    "JsonReader",
    "MediaType",
    "PdfReader",
    "PptxReader",
    "Reader",
    "ReaderError",
    "ReaderInfo",
    "ReaderRegistry",
    "Segment",
    "SkippedFile",
    "SourceDocument",
    "TextReader",
    "XlsxReader",
    "YamlReader",
    "build_registry",
    "decode_bytes",
    "looks_binary",
    "missing_dependency",
    "split_markdown",
]
