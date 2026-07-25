"""Console entry point: ``automation-miner <command>``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from automation_miner import __version__
from automation_miner.artifacts.registry import reindex
from automation_miner.artifacts.workspace import Workspace, default_workspace, read_json
from automation_miner.constraints import parse_constraint_args


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


def _resolve_workspace(args: argparse.Namespace) -> Path:
    return args.workspace or default_workspace()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="automation-miner",
        description="Mine any domain for ranked automation opportunities (AM-XXX briefs).",
    )
    parser.add_argument("--version", action="version", version=f"automation-miner {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    mine = sub.add_parser("mine", help="Run the full mining pipeline.")
    mine.add_argument("idea", nargs="?", help="Domain/idea string.")
    mine.add_argument("--file", type=Path, help="Brief file (any registered format).")
    mine.add_argument("--kb", type=Path, help="Knowledge-base folder.")
    mine.add_argument("--constraints", default="", help="Free-form constraints string.")
    mine.add_argument(
        "--constraint",
        dest="constraint_params",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Repeatable dynamic constraint parameter, e.g. --constraint agent=openclaw.",
    )
    mine.add_argument("--iterations", type=int, default=2, help="Max critique rounds.")
    mine.add_argument("--profile", default="default", help="miner.toml profile.")
    mine.add_argument(
        "--mode",
        choices=("auto", "operational", "strategy"),
        default="auto",
        help="Evidence interpretation mode. Default: auto-classify.",
    )
    mine.add_argument(
        "--dry-run",
        action="store_true",
        help="Force the mock provider: zero cost, deterministic.",
    )
    _json_arg(mine)
    _workspace_arg(mine)

    reidx = sub.add_parser("reindex", help="Rebuild registry.json from opps/.")
    _workspace_arg(reidx)

    ls = sub.add_parser("list", help="List registry entries with optional filters.")
    ls.add_argument("--layer", help="Filter by layer.")
    ls.add_argument("--min-ice", type=int, default=0, help="Minimum ICE score.")
    ls.add_argument("--tier", help="Filter by tier (vision/high/medium/low).")
    ls.add_argument("--status", help="Filter by status.")
    ls.add_argument("--domain", help="Filter by domain slug.")
    _json_arg(ls)
    _workspace_arg(ls)

    show = sub.add_parser("show", help="Print one opportunity brief (AM-XXX).")
    show.add_argument("am_id", help="Opportunity id, e.g. AM-001.")
    _workspace_arg(show)

    rep = sub.add_parser("report", help="Print the report.md of a run.")
    rep.add_argument("run_id", help="Run directory name, e.g. 2026-07-22_my-domain.")
    _workspace_arg(rep)

    summary = sub.add_parser("summary", help="Print the compact summary.json of a run.")
    summary.add_argument("run_id", help="Run directory name.")
    _workspace_arg(summary)

    readers = sub.add_parser(
        "readers", help="List document readers, their formats, and availability."
    )
    _json_arg(readers)
    _workspace_arg(readers)
    return parser


def _cmd_mine(args: argparse.Namespace) -> int:
    from automation_miner.graph.build import run_mine

    if args.idea is None and args.file is None and args.kb is None:
        print("error: provide an idea, --file, or --kb", file=sys.stderr)
        return 2
    try:
        constraint_params = parse_constraint_args(args.constraint_params)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
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
        mode=args.mode,
        constraint_params=constraint_params,
    )
    summary_path = result.get("summary_path", "")
    summary: dict[str, Any] = {}
    if summary_path and Path(summary_path).is_file():
        summary = read_json(Path(summary_path))

    if args.as_json:
        print(json.dumps(summary or {"run_id": result.get("run_id", "")}, indent=2))
        return 0

    stats = summary.get("stats", {})
    context = summary.get("context", {})
    usage = summary.get("usage", {})
    entries = summary.get("opportunities", [])

    print(f"Run: {result['run_id']}")
    if context:
        line = (
            f"Context: {context.get('included_files', 0)} file(s), "
            f"{context.get('chunks', 0)} chunks, "
            f"{context.get('evidence_tokens', 0):,} tokens "
            f"({context.get('budget_used_pct', 0)}% of budget)"
        )
        if context.get("skipped_files"):
            line += f", {context['skipped_files']} skipped"
        if context.get("digested"):
            line += ", digested"
        print(line)

    published = [e for e in entries if e.get("eligibility") == "published"]
    filtered = [e for e in entries if e.get("eligibility") != "published"]
    print(f"Opportunities: {len(published)} published" + (f", {len(filtered)} filtered" if filtered else ""))
    for entry in published:
        print(
            f"  {entry['am_id']}  ICE {entry['ice']:>3}  {entry['tier']:<6} "
            f"[{entry['layer']}] {entry['title']}"
        )
    for entry in filtered:
        reason = (entry.get("exclusion_reasons") or ["policy"])[0]
        print(f"  {entry['am_id']}  ICE {entry['ice']:>3}  filtered — {reason}")
    if stats:
        print(
            f"Portfolio: avg ICE {stats.get('avg_ice', 0)}, "
            f"median {stats.get('median_ice', 0)}, top {stats.get('top_ice', 0)}"
        )
    if usage.get("calls"):
        kind = "reported" if usage.get("exact") else "estimated"
        print(
            f"Cost: {usage['calls']} model calls, "
            f"{usage.get('total_tokens', 0):,} tokens ({kind})"
            + (f", {usage['retries']} retried" if usage.get("retries") else "")
        )
    for note in summary.get("notes", [])[:5]:
        print(f"Note: {note}")
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
    if args.tier:
        entries = [e for e in entries if e.get("tr") == args.tier]
    if args.status:
        entries = [e for e in entries if e["s"] == args.status]
    if args.domain:
        entries = [e for e in entries if e["d"] == args.domain]

    if args.as_json:
        print(json.dumps({"entries": entries, "count": len(entries)}, indent=2))
        return 0
    for e in entries:
        print(
            f"{e['i']}  ICE {e['ice']:>3}  {e.get('tr', '-'):<6} [{e['l']}] "
            f"{e['s']:<11} {e['t']}  ({e['d']})"
        )
    print(f"{len(entries)} entries")
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    ws = Workspace(_resolve_workspace(args))
    found = ws.find_opportunity(args.am_id)
    if found is None:
        print(f"Opportunity {args.am_id.upper()} not found.", file=sys.stderr)
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


def _cmd_summary(args: argparse.Namespace) -> int:
    path = Workspace(_resolve_workspace(args)).run_summary_path(args.run_id)
    if not path.is_file():
        print(f"No summary at {path}.", file=sys.stderr)
        return 1
    print(path.read_text(encoding="utf-8"))
    return 0


def _cmd_readers(args: argparse.Namespace) -> int:
    from automation_miner.models.config import load_config
    from automation_miner.readers import build_registry

    config = load_config(_resolve_workspace(args))
    registry = build_registry(config.readers)
    rows = registry.describe()

    if args.as_json:
        print(
            json.dumps(
                {
                    "readers": [
                        {
                            "name": r.name,
                            "suffixes": list(r.suffixes),
                            "media_type": r.media_type,
                            "available": r.available,
                            "reason": r.reason,
                            "source": r.source,
                        }
                        for r in rows
                    ],
                    "errors": registry.errors,
                },
                indent=2,
            )
        )
        return 0

    print(f"{'READER':<10} {'STATUS':<10} {'SOURCE':<12} FORMATS")
    for row in rows:
        status = "ready" if row.available else "unavailable"
        print(f"{row.name:<10} {status:<10} {row.source:<12} {' '.join(row.suffixes)}")
        if not row.available:
            print(f"{'':<10} → {row.reason}")
    for error in registry.errors:
        print(f"plugin error: {error}", file=sys.stderr)
    print(f"\n{len(rows)} readers, {len(registry.suffixes)} formats registered.")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    handlers = {
        "mine": _cmd_mine,
        "reindex": _cmd_reindex,
        "list": _cmd_list,
        "show": _cmd_show,
        "report": _cmd_report,
        "summary": _cmd_summary,
        "readers": _cmd_readers,
    }
    try:
        return handlers[args.command](args)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
