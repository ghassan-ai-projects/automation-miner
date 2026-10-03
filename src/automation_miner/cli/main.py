"""Console entry point: ``automation-miner <command>``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TypeAlias

from automation_miner import __version__
from automation_miner.cli import commands, lifecycle


def _workspace_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help="Workspace directory. Default: $MINER_WORKSPACE or ./mining-workspace.",
    )


def _json_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Emit machine-readable JSON instead of a table.",
    )

Subparsers: TypeAlias = "argparse._SubParsersAction[argparse.ArgumentParser]"


def _add_mine(sub: Subparsers) -> None:
    mine = sub.add_parser("mine", help="Run the full mining pipeline.")
    mine.add_argument("idea", nargs="?", help="Domain/idea string.")
    mine.add_argument("--file", type=Path, help="Brief file (any registered format).")
    mine.add_argument("--kb", type=Path, help="Knowledge-base folder.")
    mine.add_argument("--constraints", default="", help="Free-form constraints string.")
    mine.add_argument(
        "--constraint", dest="constraint_params", action="append", default=[],
        metavar="KEY=VALUE",
        help="Repeatable dynamic constraint parameter, e.g. --constraint agent=openclaw.",
    )
    mine.add_argument("--iterations", type=int, default=2, help="Max critique rounds.")
    mine.add_argument("--profile", default="default", help="miner.toml profile.")
    mine.add_argument(
        "--mode", choices=("auto", "operational", "strategy"), default="auto",
        help="Evidence interpretation mode. Default: auto-classify.",
    )
    mine.add_argument(
        "--dry-run", action="store_true", help="Force the mock provider: zero cost, deterministic."
    )
    _json_arg(mine)
    _workspace_arg(mine)


def _add_run_views(sub: Subparsers) -> None:
    """Commands that read one run or the registry."""
    resume = sub.add_parser("resume", help="Continue a failed run, reusing every completed stage.")
    resume.add_argument("run_id", help="Run directory name.")
    resume.add_argument("--dry-run", action="store_true", help="Force the mock provider.")
    _json_arg(resume)
    _workspace_arg(resume)
    _workspace_arg(sub.add_parser("reindex", help="Rebuild registry.json from opps/."))
    for name, help_text, arg_help in (
        ("show", "Print one opportunity brief (AM-XXX).", "Opportunity id, e.g. AM-001."),
        ("report", "Print the report.md of a run.", "Run directory name."),
        ("summary", "Print the compact summary.json of a run.", "Run directory name."),
    ):
        command = sub.add_parser(name, help=help_text)
        command.add_argument("am_id" if name == "show" else "run_id", help=arg_help)
        _workspace_arg(command)


def _add_list(sub: Subparsers) -> None:
    ls = sub.add_parser("list", help="List registry entries with optional filters.")
    ls.add_argument("--layer", help="Filter by layer.")
    ls.add_argument("--min-ice", type=int, default=0, help="Minimum ICE score.")
    ls.add_argument("--tier", help="Filter by tier (vision/high/medium/low).")
    ls.add_argument("--status", help="Filter by status.")
    ls.add_argument("--domain", help="Filter by domain slug.")
    _json_arg(ls)
    _workspace_arg(ls)


def _add_evaluation(sub: Subparsers) -> None:
    evaluate = sub.add_parser(
        "evaluate", help="Grade a run: deterministic brief lint plus an independent judge model."
    )
    evaluate.add_argument("run_id", help="Run directory name.")
    evaluate.add_argument(
        "--no-judge", action="store_true", help="Lint only; skip the judge model (zero cost)."
    )
    evaluate.add_argument("--profile", default="default", help="miner.toml profile.")
    evaluate.add_argument("--dry-run", action="store_true", help="Use the mock judge (zero cost).")
    _json_arg(evaluate)
    _workspace_arg(evaluate)
    readers = sub.add_parser(
        "readers", help="List document readers, their formats, and availability."
    )
    _json_arg(readers)
    _workspace_arg(readers)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="automation-miner",
        description="Mine any domain for ranked automation opportunities (AM-XXX briefs).",
    )
    parser.add_argument("--version", action="version", version=f"automation-miner {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    for add in (_add_mine, _add_run_views, _add_list, _add_evaluation):
        add(sub)
    lifecycle.add_lifecycle(sub, _workspace_arg, _json_arg)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    handlers = {
        "mine": commands.cmd_mine,
        "resume": commands.cmd_resume,
        "reindex": commands.cmd_reindex,
        "list": commands.cmd_list,
        "show": commands.cmd_show,
        "report": commands.cmd_report,
        "summary": commands.cmd_summary,
        "evaluate": commands.cmd_evaluate,
        "readers": commands.cmd_readers,
        "status": lifecycle.cmd_status,
        "outcome": lifecycle.cmd_outcome,
        "outcomes": lifecycle.cmd_outcomes,
        "export": lifecycle.cmd_export,
    }
    try:
        return handlers[args.command](args)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
