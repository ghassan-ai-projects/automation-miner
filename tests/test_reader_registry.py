"""Reader registry: suffix routing, fallbacks, options, and plugins."""

from __future__ import annotations

from pathlib import Path

import pytest

from automation_miner.readers import (
    BaseReader,
    MediaType,
    ReaderError,
    Segment,
    build_registry,
)
from automation_miner.readers.registry import NEVER_TEXT, ReaderRegistry, _validate

from pdf_fixtures import make_pdf


def test_builtin_registry_claims_expected_suffixes() -> None:
    registry = build_registry()
    for suffix in (".md", ".txt", ".json", ".yaml", ".csv", ".html", ".pdf", ".docx", ".xlsx"):
        assert suffix in registry.suffixes, suffix
    assert not registry.errors


def test_unknown_text_suffix_falls_back_to_text(tmp_path: Path) -> None:
    path = tmp_path / "report.sql"
    path.write_text("SELECT count(*) FROM claims; -- run by hand weekly\n", encoding="utf-8")
    document = build_registry().read(path)
    assert document.reader == "text"
    assert "read as text" in str(document.meta["fallback"])


def test_binary_suffix_never_falls_back_to_text(tmp_path: Path) -> None:
    """An uncompressed PDF looks textual in its header — the suffix guard must win."""
    path = tmp_path / "regulation.pdf"
    path.write_bytes(make_pdf(["text"]))
    registry = build_registry({"disabled": ["pdf"]})
    with pytest.raises(ReaderError, match="uv sync --extra pdf"):
        registry.read(path)
    assert ".pdf" in NEVER_TEXT


def test_unregistered_binary_is_skipped_with_reason(tmp_path: Path) -> None:
    path = tmp_path / "logo.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(range(256)))
    with pytest.raises(ReaderError, match="binary"):
        build_registry().read(path)


def test_size_cap_and_empty_file(tmp_path: Path) -> None:
    big = tmp_path / "huge.txt"
    big.write_text("x" * 5_000, encoding="utf-8")
    with pytest.raises(ReaderError, match="max_file_bytes"):
        build_registry({"max_file_bytes": 1_000}).read(big)

    empty = tmp_path / "empty.md"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(ReaderError, match="empty"):
        build_registry().read(empty)


def test_per_reader_options_from_config(tmp_path: Path) -> None:
    path = tmp_path / "rows.csv"
    path.write_text("\n".join(["a,b"] + [f"{i},{i}" for i in range(100)]), encoding="utf-8")
    small = build_registry({"csv": {"sample_rows": 4}}).read(path)
    large = build_registry({"csv": {"sample_rows": 40}}).read(path)
    assert large.chars > small.chars


def test_disabled_reader_is_not_registered() -> None:
    registry = build_registry({"disabled": ["pptx", "xlsx"]})
    assert "pptx" not in registry.registrations
    assert ".xlsx" not in registry.suffixes


def test_enabled_allowlist_restricts_registry() -> None:
    registry = build_registry({"enabled": ["text", "json"]})
    assert set(registry.registrations) == {"text", "json"}
    assert ".pdf" not in registry.suffixes


def test_custom_reader_from_config_needs_no_package_change(tmp_path: Path) -> None:
    registry = build_registry(
        {"custom": [{"suffixes": [".vtt"], "name": "vtt", "factory": f"{__name__}:_VttReader"}]}
    )
    path = tmp_path / "standup.vtt"
    path.write_text("WEBVTT\n\n00:00:01.000 --> 00:00:04.000\nManual reconciliation.\n", "utf-8")
    document = registry.read(path)
    assert document.reader == "vtt"
    assert "Manual reconciliation." in document.text()
    assert [r.source for r in registry.describe() if r.name == "vtt"] == ["miner.toml"]


def test_custom_reader_outranks_builtin_for_same_suffix() -> None:
    registry = build_registry(
        {"custom": [{"suffixes": [".md"], "name": "vtt", "factory": f"{__name__}:_VttReader"}]}
    )
    assert registry.reader_for(Path("x.md")).name == "vtt"


def test_broken_plugin_is_reported_not_fatal(tmp_path: Path) -> None:
    registry = build_registry({"custom": [{"suffixes": [".zzz"], "factory": "nope.absent:Thing"}]})
    assert any("failed to load" in error for error in registry.errors)
    path = tmp_path / "still.md"
    path.write_text("# works\n", encoding="utf-8")
    assert registry.read(path).reader == "text"


def test_registry_rejects_malformed_readers() -> None:
    class NoSuffixes(BaseReader):
        name = "broken"
        suffixes = ()

    registry = ReaderRegistry()
    registry.register(NoSuffixes(), source="test")
    assert registry.registrations == {}
    assert "declares no suffixes" in registry.errors[0]
    assert "no usable 'name'" in _validate(object())


def test_describe_reports_availability() -> None:
    rows = {row.name: row for row in build_registry().describe()}
    assert rows["text"].available
    assert rows["csv"].media_type == "tabular"
    assert all(row.source == "builtin" for row in rows.values())


class _VttReader(BaseReader):
    """Stand-in for a third-party reader, referenced by config in the tests above."""

    name = "vtt"
    suffixes = (".vtt",)
    media_type = MediaType.TEXT

    def parse(self, path: Path, data: bytes) -> list[Segment]:
        lines = [
            line.strip()
            for line in self.decode(data).split("\n")
            if line.strip() and line.strip() != "WEBVTT" and "-->" not in line
        ]
        return [Segment(text=" ".join(lines), locator="transcript")]
