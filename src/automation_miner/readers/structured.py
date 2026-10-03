"""JSON, JSON Lines, and YAML readers.

Two deliberate choices here, both about context budget:

* **Parse failures fall back to raw text.** Previously one unparseable ``.json``
  in a knowledge base aborted the whole run. A truncated export is still useful
  evidence, so it is read as text and the parse failure recorded in ``meta``.
* **Large structures are summarized, not dumped.** A 20k-record array tells the
  miner nothing extra past its shape and a sample, and re-serializing it with
  ``indent=2`` used to nearly double its character cost.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from automation_miner.readers.base import BaseReader, MediaType, Segment

# Below this, pretty-print for readability; above it, summarize.
READABLE_LIMIT = 4_000
SAMPLE_HEAD = 5
SAMPLE_TAIL = 2


def _dumps(value: Any, compact: bool = False) -> str:
    if compact:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _describe_records(records: list[Any], label: str) -> list[Segment]:
    """Shape + sample for a long homogeneous array."""
    keys: list[str] = []
    for item in records[:200]:
        if isinstance(item, dict):
            for key in item:
                if key not in keys:
                    keys.append(str(key))
    head = records[:SAMPLE_HEAD]
    tail = records[-SAMPLE_TAIL:] if len(records) > SAMPLE_HEAD + SAMPLE_TAIL else []
    lines = [
        f"{label}: array of {len(records)} records.",
        f"Fields ({len(keys)}): {', '.join(keys)}" if keys else "Records are not objects.",
        "",
        f"First {len(head)} records:",
        _dumps(head),
    ]
    if tail:
        lines += ["", f"Last {len(tail)} records:", _dumps(tail)]
    return [Segment(text="\n".join(lines), locator=f"{label} (shape + sample)")]


def _segments_for(value: Any, label: str) -> list[Segment]:
    """Render a parsed structure within a sensible character cost."""
    if isinstance(value, list) and len(value) > SAMPLE_HEAD + SAMPLE_TAIL:
        compact = _dumps(value, compact=True)
        if len(compact) > READABLE_LIMIT:
            return _describe_records(value, label)
    rendered = _dumps(value)
    if len(rendered) > READABLE_LIMIT:
        rendered = _dumps(value, compact=True)
    return [Segment(text=rendered, locator=label)]


class JsonReader(BaseReader):
    """``.json`` plus line-delimited ``.jsonl``/``.ndjson``."""

    name = "json"
    suffixes = (".json", ".jsonl", ".ndjson")
    media_type = MediaType.STRUCTURED

    def parse(self, path: Path, data: bytes) -> list[Segment]:
        text = self.decode(data)
        if path.suffix.lower() in {".jsonl", ".ndjson"}:
            return self._parse_lines(text)
        try:
            value = json.loads(text)
        except (json.JSONDecodeError, ValueError) as exc:
            self.note("parse_error", f"invalid JSON, read as text: {exc}")
            return [Segment(text=text, locator="raw (unparseable JSON)")]
        return _segments_for(value, path.name)

    def _parse_lines(self, text: str) -> list[Segment]:
        records: list[Any] = []
        bad = 0
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except (json.JSONDecodeError, ValueError):
                bad += 1
        if bad:
            self.note("parse_error", f"{bad} unparseable line(s) skipped")
        if not records:
            return [Segment(text=text, locator="raw (no parseable JSON lines)")]
        return _segments_for(records, "records")



class YamlReader(BaseReader):
    """YAML, including multi-document streams."""

    name = "yaml"
    suffixes = (".yaml", ".yml")
    media_type = MediaType.STRUCTURED

    def parse(self, path: Path, data: bytes) -> list[Segment]:
        text = self.decode(data)
        try:
            documents = [doc for doc in yaml.safe_load_all(text) if doc is not None]
        except yaml.YAMLError as exc:
            self.note("parse_error", f"invalid YAML, read as text: {exc}")
            return [Segment(text=text, locator="raw (unparseable YAML)")]
        if not documents:
            return [Segment(text=text, locator="raw (empty YAML)")]
        if len(documents) == 1:
            return _segments_for(documents[0], path.name)
        segments: list[Segment] = []
        for index, document in enumerate(documents, 1):
            segments += _segments_for(document, f"{path.name} doc {index}")
        return segments

