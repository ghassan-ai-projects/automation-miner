"""Stakeholder one-pager export."""

from __future__ import annotations

import json
from pathlib import Path

from automation_miner.artifacts.export import render_one_pager
from automation_miner.artifacts.lifecycle import set_status
from automation_miner.artifacts.layout import RunLayout
from automation_miner.cli.main import main
from automation_miner.graph.runner import run_mine
from automation_miner.mcp.tools import dispatch


def _run(root: Path) -> Path:
    result = run_mine(workspace_path=root, idea="Claims intake at a regional insurer", dry_run=True)
    return Path(str(result["summary_path"])).parent


def test_one_pager_is_self_contained_and_shows_lifecycle_status(tmp_path: Path) -> None:
    run_dir = _run(tmp_path)
    set_status(tmp_path, "AM-002", "evaluating")
    html = render_one_pager(run_dir, tmp_path, top=2)
    assert html.startswith("<!doctype html>") and "<script" not in html
    assert "http://" not in html and "https://" not in html
    assert html.count('<article class="card"') == 2
    assert "evaluating" in html and "How success is measured" in html


def test_one_pager_escapes_brief_text(tmp_path: Path) -> None:
    run_dir = _run(tmp_path)
    path = RunLayout(run_dir).opportunities
    payload = json.loads(path.read_text())
    payload["opportunities"][0]["draft"]["title"] = '<img src=x onerror="alert(1)">'
    path.write_text(json.dumps(payload))
    html = render_one_pager(run_dir)
    assert "<img" not in html and "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;" in html


def test_cli_and_mcp_export(tmp_path: Path, capsys) -> None:
    run_dir = _run(tmp_path)
    out = tmp_path / "share" / "page.html"
    assert main(["export", run_dir.name, "--out", str(out), "--workspace", str(tmp_path)]) == 0
    assert out.is_file() and str(out) in capsys.readouterr().out
    response = dispatch("export_one_pager", {"run_id": run_dir.name}, tmp_path)
    assert response.success and Path(response.data["path"]) == RunLayout(run_dir).one_pager
    missing = dispatch("export_one_pager", {"run_id": "2026-01-01_nope"}, tmp_path)
    assert not missing.success and missing.error.code == "not_found"
