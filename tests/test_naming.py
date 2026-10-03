"""Readable report titles for file and knowledge-base input."""

from __future__ import annotations

from pathlib import Path

from automation_miner.ingest import ingest_file, ingest_kb
from automation_miner.ingest.naming import document_title, readable_name
from automation_miner.readers.base import MediaType, Segment, SourceDocument


def _doc(*locators: str) -> SourceDocument:
    segments = [Segment(text="body", locator=loc) for loc in locators]
    return SourceDocument(path="x.md", reader="text", media_type=MediaType.TEXT, segments=segments)


def test_readable_name_humanizes_paths() -> None:
    assert readable_name("claims-intake") == "Claims intake"
    assert readable_name("01_sop_motor-claims") == "Sop motor claims"
    assert readable_name("DHL-Germany") == "DHL Germany"
    assert readable_name("---") == "---"


def test_document_title_uses_the_top_heading_only() -> None:
    assert document_title(_doc("", "# Board memo — Strategy 2027 > ## Goals")) == (
        "Board memo — Strategy 2027"
    )
    assert document_title(_doc("## Only a subsection")) == ""
    assert document_title(_doc("# " + "x" * 200)) == ""


def test_file_title_prefers_heading_but_keeps_the_path_slug(tmp_path: Path) -> None:
    path = tmp_path / "hospital-strategy-memo.md"
    path.write_text("# Board memo — Digital Strategy\n\nWe plan to automate intake.\n")
    packet = ingest_file(path)
    assert packet.domain == "Board memo — Digital Strategy"
    assert packet.domain_slug == "hospital-strategy-memo"


def test_kb_title_is_humanized_and_slug_unchanged(tmp_path: Path) -> None:
    folder = tmp_path / "claims-intake"
    folder.mkdir()
    (folder / "notes.md").write_text("# Notes\n\nIntake takes 9 minutes per claim.\n")
    packet = ingest_kb(folder)
    assert packet.domain == "Claims intake"
    assert packet.domain_slug == "claims-intake"
