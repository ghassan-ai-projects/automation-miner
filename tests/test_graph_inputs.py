"""End-to-end runs over file and knowledge-base inputs."""

from __future__ import annotations

from pathlib import Path

from automation_miner.artifacts.workspace import read_json
from automation_miner.artifacts.layout import RunLayout
from automation_miner.graph.runner import run_mine
import pytest


def test_run_with_kb_input(workspace: Path, tmp_path: Path) -> None:
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "notes.md").write_text("# Domain notes\nManual reporting everywhere.", "utf-8")
    result = run_mine(workspace_path=workspace, kb=kb, dry_run=True)
    ctx = read_json(RunLayout(Path(result["run_dir"])).context)
    assert ctx["source_kind"] == "kb"
    assert "Manual reporting" in ctx["overview"]
    assert ctx["chunks"][0]["id"] == "S1"
    assert ctx["stats"]["included_files"] == 1


def test_run_with_mixed_format_kb(workspace: Path, tmp_path: Path) -> None:
    """Every registered format contributes, and unreadable files are reported."""
    pytest.importorskip("pypdf")
    from pdf_fixtures import make_pdf

    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "sop.md").write_text("# SOP\n\n400 claims/day by hand.", encoding="utf-8")
    (kb / "rules.pdf").write_bytes(make_pdf(["Audit trail retained 10 years."]))
    (kb / "volumes.csv").write_text(
        "month,claims\n2026-01,8000\n2026-02,8100\n", encoding="utf-8"
    )
    (kb / "broken.json").write_text('{"a": [1,', encoding="utf-8")
    (kb / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(range(256)))

    result = run_mine(workspace_path=workspace, kb=kb, dry_run=True)
    ctx = read_json(RunLayout(Path(result["run_dir"])).context)

    assert ctx["stats"]["included_files"] == 4
    assert ctx["stats"]["skipped_files"] == 1
    sources = {chunk["source"] for chunk in ctx["chunks"]}
    assert sources == {"sop.md", "rules.pdf", "volumes.csv", "broken.json"}
    assert any(c["locator"] == "p.1" for c in ctx["chunks"])

    report = (Path(result["run_dir"]) / "report.md").read_text(encoding="utf-8")
    assert "## Files Not Read" in report
    assert "logo.png" in report


def test_evidence_refs_resolve_against_the_index(workspace: Path, tmp_path: Path) -> None:
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "notes.md").write_text("# Notes\n\nManual rework costs 4h/week.", encoding="utf-8")
    result = run_mine(workspace_path=workspace, kb=kb, dry_run=True)
    opps = result["opportunities"]
    assert all(o["draft"]["evidence_refs"] for o in opps)
    assert all(o["unresolved_refs"] == [] for o in opps)
