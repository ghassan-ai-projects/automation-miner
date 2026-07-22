"""CLI smoke tests — every subcommand, all offline."""

from __future__ import annotations

from pathlib import Path

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
