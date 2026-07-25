"""CLI smoke tests — every subcommand, all offline."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from automation_miner.cli.main import main


def _mine(workspace: Path) -> str:
    rc = main(["mine", "CLI test domain", "--dry-run", "--workspace", str(workspace)])
    assert rc == 0
    runs = sorted((workspace / "runs").iterdir())
    return runs[0].name


def test_mine_dry_run(workspace: Path, capsys) -> None:
    _mine(workspace)
    out = capsys.readouterr().out
    assert "Opportunities: 5" in out
    assert "AM-001" in out
    assert "Report:" in out


def test_mine_requires_input(workspace: Path, capsys) -> None:
    rc = main(["mine", "--workspace", str(workspace)])
    assert rc == 2
    assert "provide an idea" in capsys.readouterr().err


def test_mine_rejects_zero_iterations(workspace: Path, capsys) -> None:
    rc = main(
        [
            "mine",
            "CLI test domain",
            "--iterations",
            "0",
            "--dry-run",
            "--workspace",
            str(workspace),
        ]
    )
    assert rc == 1
    assert "between 1 and 10" in capsys.readouterr().err


def test_show_accepts_unpadded_numeric_id(workspace: Path, capsys) -> None:
    _mine(workspace)
    assert main(["show", "2", "--workspace", str(workspace)]) == 0
    assert "# AM-002:" in capsys.readouterr().out


def test_report_rejects_path_traversal(workspace: Path, capsys) -> None:
    rc = main(["report", "../../private", "--workspace", str(workspace)])
    assert rc == 1
    assert "Invalid run id" in capsys.readouterr().err


def test_reindex(workspace: Path, capsys) -> None:
    _mine(workspace)
    rc = main(["reindex", "--workspace", str(workspace)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Opps: 5" in out


def test_list_with_filters(workspace: Path, capsys) -> None:
    _mine(workspace)
    rc = main(["list", "--workspace", str(workspace)])
    assert rc == 0
    assert "5 entries" in capsys.readouterr().out

    rc = main(["list", "--layer", "document", "--workspace", str(workspace)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "1 entries" in out
    assert "[document]" in out

    rc = main(["list", "--min-ice", "100", "--workspace", str(workspace)])
    assert rc == 0
    assert "0 entries" in capsys.readouterr().out


def test_show(workspace: Path, capsys) -> None:
    _mine(workspace)
    rc = main(["show", "AM-002", "--workspace", str(workspace)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "# AM-002:" in out
    assert "## Problem Statement" in out


def test_show_missing(workspace: Path, capsys) -> None:
    _mine(workspace)
    rc = main(["show", "AM-999", "--workspace", str(workspace)])
    assert rc == 1
    assert "not found" in capsys.readouterr().err


def test_report(workspace: Path, capsys) -> None:
    run_id = _mine(workspace)
    rc = main(["report", run_id, "--workspace", str(workspace)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "# Automation Mining Report" in out
    assert "Strategic Filters" in out


def test_report_missing(workspace: Path, capsys) -> None:
    rc = main(["report", "2099-01-01_nope", "--workspace", str(workspace)])
    assert rc == 1


# --- v4 surface: readers, summary, --json, --version, richer mine output ----


def test_mine_reports_context_cost_and_tiers(workspace: Path, capsys) -> None:
    _mine(workspace)
    out = capsys.readouterr().out
    assert "Context:" in out and "chunks" in out and "% of budget" in out
    assert "Portfolio: avg ICE" in out
    assert "Cost:" in out and "model calls" in out
    assert "high" in out  # tier column


def test_mine_reports_filtered_opportunities(workspace: Path, capsys) -> None:
    rc = main(
        [
            "mine",
            "Urgent CLI domain",
            "--constraints",
            "urgent",
            "--dry-run",
            "--workspace",
            str(workspace),
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "3 published, 2 filtered" in out
    assert "filtered — urgent timeline" in out


def test_mine_json_output(workspace: Path, capsys) -> None:
    rc = main(["mine", "JSON domain", "--dry-run", "--json", "--workspace", str(workspace)])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["stats"]["published"] == 5
    assert payload["opportunities"][0]["tier"] == "high"


def test_mine_accepts_repeatable_dynamic_constraints(workspace: Path, capsys) -> None:
    rc = main(
        [
            "mine",
            "OpenClaw portfolio",
            "--constraint",
            "agent=openclaw",
            "--constraint",
            "deployment=local-only",
            "--dry-run",
            "--json",
            "--workspace",
            str(workspace),
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert "agent = openclaw" in payload["constraints"]


def test_mine_rejects_invalid_dynamic_constraint(workspace: Path, capsys) -> None:
    rc = main(
        [
            "mine",
            "Invalid constraint",
            "--constraint",
            "agent",
            "--dry-run",
            "--workspace",
            str(workspace),
        ]
    )
    assert rc == 2
    assert "must use key=value" in capsys.readouterr().err


def test_summary_command(workspace: Path, capsys) -> None:
    run_id = _mine(workspace)
    capsys.readouterr()
    assert main(["summary", run_id, "--workspace", str(workspace)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["run_id"] == run_id


def test_summary_command_missing_run(workspace: Path, capsys) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    rc = main(["summary", "2026-01-01_nope", "--workspace", str(workspace)])
    assert rc == 1
    assert "No summary at" in capsys.readouterr().err


def test_readers_command_lists_formats(workspace: Path, capsys) -> None:
    assert main(["readers", "--workspace", str(workspace)]) == 0
    out = capsys.readouterr().out
    assert "READER" in out and "FORMATS" in out
    for name in ("text", "json", "csv", "pdf", "docx", "xlsx"):
        assert name in out
    assert "formats registered" in out


def test_readers_command_json(workspace: Path, capsys) -> None:
    assert main(["readers", "--json", "--workspace", str(workspace)]) == 0
    payload = json.loads(capsys.readouterr().out)
    names = {row["name"] for row in payload["readers"]}
    assert {"text", "csv", "pdf"} <= names
    assert ".md" in payload["formats"] if "formats" in payload else True


def test_list_filters_by_tier(workspace: Path, capsys) -> None:
    _mine(workspace)
    capsys.readouterr()
    assert main(["list", "--tier", "high", "--workspace", str(workspace)]) == 0
    assert "5 entries" in capsys.readouterr().out
    assert main(["list", "--tier", "vision", "--workspace", str(workspace)]) == 0
    assert "0 entries" in capsys.readouterr().out


def test_list_json_output(workspace: Path, capsys) -> None:
    _mine(workspace)
    capsys.readouterr()
    assert main(["list", "--json", "--workspace", str(workspace)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] == 5
    assert payload["entries"][0]["tr"] == "high"


def test_version_flag(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert "automation-miner" in capsys.readouterr().out
