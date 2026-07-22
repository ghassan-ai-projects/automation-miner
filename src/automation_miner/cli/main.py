"""Console entry point: ``automation-miner <command>``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from automation_miner.artifacts.registry import reindex
from automation_miner.artifacts.workspace import Workspace, default_workspace, read_json


def _workspace_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help="Workspace directory. Default: $MINER_WORKSPACE or ./mining-workspace.",
    )


def _resolve_workspace(args: argparse.Namespace) -> Path:
    return args.workspace or default_workspace()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="automation-miner",
        description="Mine any domain for ranked automation opportunities (AM-XXX briefs).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    mine = sub.add_parser("mine", help="Run the full mining pipeline.")
    mine.add_argument("idea", nargs="?", help="Domain/idea string.")
    mine.add_argument("--file", type=Path, help="Brief file (.md/.txt/.json/.yaml).")
    mine.add_argument("--kb", type=Path, help="Knowledge-base folder.")
    mine.add_argument("--constraints", default="", help="Free-form constraints string.")
    mine.add_argument("--iterations", type=int, default=2, help="Max critique rounds.")
    mine.add_argument("--profile", default="default", help="miner.toml profile.")
    mine.add_argument(
        "--dry-run",
        action="store_true",
        help="Force the mock provider: zero cost, deterministic.",
    )
    _workspace_arg(mine)

    reidx = sub.add_parser("reindex", help="Rebuild registry.json from opps/.")
    _workspace_arg(reidx)

    ls = sub.add_parser("list", help="List registry entries with optional filters.")
    ls.add_argument("--layer", help="Filter by layer.")
    ls.add_argument("--min-ice", type=int, default=0, help="Minimum ICE score.")
    ls.add_argument("--status", help="Filter by status.")
    _workspace_arg(ls)

    show = sub.add_parser("show", help="Print one opportunity brief (AM-XXX).")
    show.add_argument("am_id", help="Opportunity id, e.g. AM-001.")
    _workspace_arg(show)

    rep = sub.add_parser("report", help="Print the report.md of a run.")
    rep.add_argument("run_id", help="Run directory name, e.g. 2026-07-22_my-domain.")
    _workspace_arg(rep)
    return parser


def _cmd_mine(args: argparse.Namespace) -> int:
    from automation_miner.graph.build import run_mine

    if not args.dry_run and args.idea is None and args.file is None and args.kb is None:
        print("error: provide an idea, --file, or --kb", file=sys.stderr)
        return 2
    result = run_mine(
        workspace_path=_resolve_workspace(args),
        idea=args.idea,
        file=args.file,
        kb=args.kb,
        constraints=args.constraints,
        max_iterations=args.iterations,
        profile=args.profile,
        dry_run=args.dry_run,
    )
    opps = result.get("opportunities", [])
    print(f"Run: {result['run_id']}")
    print(f"Opportunities: {len(opps)}")
    for o in opps:
        print(f"  {o['am_id']}  ICE {o['ice']:>3}  [{o['draft']['layer']}] {o['draft']['title']}")
    print(f"Report: {result.get('report_path', '')}")
    return 0


def _cmd_reindex(args: argparse.Namespace) -> int:
    root = _resolve_workspace(args)
    registry = reindex(root)
    s = registry["stats"]
    print(f"Registry written: {root / 'registry.json'}")
    print(f"  Runs: {s['runs']} | Opps: {s['opps']} | Avg ICE: {s['avg_ice']}")
    print(f"  Top: {s['top_id']} ({s['top_ice']}) | Bottom ICE: {s['bot_ice']}")
    return 0


def _load_registry(root: Path) -> dict:
    path = root / "registry.json"
    if not path.is_file():
        raise SystemExit(f"No registry at {path}. Run a mine or reindex first.")
    return read_json(path)


def _cmd_list(args: argparse.Namespace) -> int:
    registry = _load_registry(_resolve_workspace(args))
    entries = registry.get("entries", [])
    if args.layer:
        entries = [e for e in entries if e["l"] == args.layer]
    if args.min_ice:
        entries = [e for e in entries if e["ice"] >= args.min_ice]
    if args.status:
        entries = [e for e in entries if e["s"] == args.status]
    for e in entries:
        print(f"{e['i']}  ICE {e['ice']:>3}  [{e['l']}] {e['s']:<11} {e['t']}  ({e['d']})")
    print(f"{len(entries)} entries")
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    ws = Workspace(_resolve_workspace(args))
    found = ws.find_opportunity(args.am_id)
    if found is None:
        am_id = args.am_id.upper()
        print(f"Opportunity {am_id} not found.", file=sys.stderr)
        return 1
    _, path = found
    print(path.read_text(encoding="utf-8"))
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    path = Workspace(_resolve_workspace(args)).run_report_path(args.run_id)
    if not path.is_file():
        print(f"No report at {path}.", file=sys.stderr)
        return 1
    print(path.read_text(encoding="utf-8"))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    handlers = {
        "mine": _cmd_mine,
        "reindex": _cmd_reindex,
        "list": _cmd_list,
        "show": _cmd_show,
        "report": _cmd_report,
    }
    try:
        return handlers[args.command](args)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
