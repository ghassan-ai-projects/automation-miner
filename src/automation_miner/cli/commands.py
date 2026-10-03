"""CLI command handlers: one function per ``automation-miner`` subcommand."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from automation_miner.artifacts.registry import reindex
from automation_miner.cli import display
from automation_miner.artifacts.workspace import Workspace, default_workspace, read_json
from automation_miner.constraints import parse_constraint_args


def _resolve_workspace(args: argparse.Namespace) -> Path:
    return args.workspace or default_workspace()


def _summary(result: dict[str, Any]) -> dict[str, Any]:
    path = result.get("summary_path", "")
    return read_json(Path(path)) if path and Path(path).is_file() else {}


def cmd_mine(args: argparse.Namespace) -> int:
    from automation_miner.graph.runner import run_mine

    if args.idea is None and args.file is None and args.kb is None:
        print("error: provide an idea, --file, or --kb", file=sys.stderr)
        return 2
    try:
        constraint_params = parse_constraint_args(args.constraint_params)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    stream = display.stream_for(args.as_json)
    result = run_mine(
        workspace_path=_resolve_workspace(args), idea=args.idea, file=args.file, kb=args.kb,
        constraints=args.constraints, max_iterations=args.iterations, profile=args.profile,
        dry_run=args.dry_run, mode=args.mode, constraint_params=constraint_params,
        preflight_callback=display.preflight_printer(stream),
        progress_callback=display.progress_printer(stream),
    )
    summary = _summary(dict(result))
    if args.as_json:
        print(json.dumps(summary or {"run_id": result.get("run_id", "")}, indent=2))
    else:
        print("\n".join(display.run_lines(dict(result), summary)))
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    from automation_miner.graph.runner import resume_run

    result = resume_run(
        workspace_path=_resolve_workspace(args), run_id=args.run_id, dry_run=args.dry_run,
        progress_callback=display.progress_printer(display.stream_for(args.as_json)),
    )
    summary = _summary(dict(result))
    if args.as_json:
        print(json.dumps(summary, indent=2))
    else:
        print("\n".join(display.run_lines(dict(result), summary)))
    return 0


def cmd_reindex(args: argparse.Namespace) -> int:
    root = _resolve_workspace(args)
    registry = reindex(root)
    s = registry["stats"]
    print(f"Registry written: {root / 'registry.json'}")
    print(f"  Runs: {s['runs']} | Opps: {s['opps']} | Avg ICE: {s['avg_ice']}")
    print(f"  Top: {s['top_id']} ({s['top_ice']}) | Bottom ICE: {s['bot_ice']}")
    return 0


def _load_registry(root: Path) -> dict[str, Any]:
    path = root / "registry.json"
    if not path.is_file():
        raise SystemExit(f"No registry at {path}. Run a mine or reindex first.")
    return read_json(path)


def cmd_list(args: argparse.Namespace) -> int:
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


def cmd_show(args: argparse.Namespace) -> int:
    ws = Workspace(_resolve_workspace(args))
    found = ws.find_opportunity(args.am_id)
    if found is None:
        print(f"Opportunity {args.am_id.upper()} not found.", file=sys.stderr)
        return 1
    _, path = found
    print(path.read_text(encoding="utf-8"))
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    path = Workspace(_resolve_workspace(args)).run_report_path(args.run_id)
    if not path.is_file():
        print(f"No report at {path}.", file=sys.stderr)
        return 1
    print(path.read_text(encoding="utf-8"))
    return 0


def cmd_summary(args: argparse.Namespace) -> int:
    path = Workspace(_resolve_workspace(args)).run_summary_path(args.run_id)
    if not path.is_file():
        print(f"No summary at {path}.", file=sys.stderr)
        return 1
    print(path.read_text(encoding="utf-8"))
    return 0


def cmd_evaluate(args: argparse.Namespace) -> int:
    from automation_miner.evaluation import evaluate_run, render_evaluation
    from automation_miner.models.client import MinerModel
    from automation_miner.models.config import load_config

    root = _resolve_workspace(args)
    run_dir = Workspace(root).run_summary_path(args.run_id).parent
    if not (run_dir / "summary.json").is_file():
        print(f"No completed run at {run_dir}.", file=sys.stderr)
        return 1
    model = (
        None
        if args.no_judge
        else MinerModel(load_config(root, args.profile), dry_run=args.dry_run)
    )
    try:
        evaluation = evaluate_run(run_dir, root, model)
    finally:
        if model is not None:
            model.close()
    if args.as_json:
        print(evaluation.model_dump_json(indent=2))
    else:
        print(render_evaluation(evaluation), end="")
    return 0


def cmd_readers(args: argparse.Namespace) -> int:
    from automation_miner.models.config import load_config
    from automation_miner.readers import build_registry

    registry = build_registry(load_config(_resolve_workspace(args)).readers)
    rows = registry.describe()
    if args.as_json:
        readers = [
            {"name": r.name, "suffixes": list(r.suffixes), "media_type": r.media_type,
             "available": r.available, "reason": r.reason, "source": r.source}
            for r in rows
        ]
        print(json.dumps({"readers": readers, "errors": registry.errors}, indent=2))
        return 0
    print("\n".join(display.reader_lines(rows, registry.errors, len(registry.suffixes))))
    for error in registry.errors:
        print(f"plugin error: {error}", file=sys.stderr)
    return 0