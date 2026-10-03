"""CLI handlers for the post-publication lifecycle: status, outcome, outcomes."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from automation_miner.artifacts.lifecycle import outcome_rows, record_outcome, set_status
from automation_miner.artifacts.workspace import default_workspace


def _root(args: argparse.Namespace) -> Path:
    return args.workspace or default_workspace()


def cmd_status(args: argparse.Namespace) -> int:
    event = set_status(_root(args), args.am_id, args.status, args.note)
    previous = event.previous.value if event.previous else "identified"
    print(f"{event.am_id}: {previous} → {event.status.value if event.status else ''}")
    return 0


def cmd_outcome(args: argparse.Namespace) -> int:
    event = record_outcome(
        _root(args), args.am_id, args.metric, args.measured,
        baseline=args.baseline, verdict=args.verdict, note=args.note,
    )
    change = " → ".join(part for part in (event.baseline, event.measured) if part)
    print(f"{event.am_id}: {event.metric}: {change} ({event.verdict or 'no verdict'})")
    return 0


def _calibration(rows: list[dict[str, Any]]) -> list[str]:
    """Verdicts per tier: whether high-ICE briefs deliver more often than low ones."""
    counts = Counter((row["tier"] or "unknown", row["verdict"] or "none") for row in rows)
    tiers = sorted({tier for tier, _ in counts})
    return [
        f"  {tier:<8} " + "  ".join(
            f"{verdict} {counts[(tier, verdict)]}" for verdict in ("met", "partial", "missed", "none")
            if counts[(tier, verdict)]
        )
        for tier in tiers
    ]


def cmd_outcomes(args: argparse.Namespace) -> int:
    rows = outcome_rows(_root(args))
    if args.as_json:
        print(json.dumps({"outcomes": rows, "count": len(rows)}, indent=2))
        return 0
    for row in rows:
        change = " → ".join(part for part in (row["baseline"], row["measured"]) if part)
        print(
            f"{row['am_id']}  ICE {row['ice'] if row['ice'] is not None else '-':>3}  "
            f"{row['verdict'] or '-':<7} {row['metric']}: {change}"
        )
    print(f"{len(rows)} measured outcomes")
    if rows:
        print("By tier:", *_calibration(rows), sep="\n")
    return 0


def add_lifecycle(sub: Any, workspace_arg: Any, json_arg: Any) -> None:
    status = sub.add_parser("status", help="Move a published brief to a lifecycle status.")
    status.add_argument("am_id", help="Opportunity id, e.g. AM-001.")
    status.add_argument(
        "status", help="identified, evaluating, designing, implementing, live, or deprecated."
    )
    status.add_argument("--note", default="", help="Why it moved.")
    workspace_arg(status)
    outcome = sub.add_parser("outcome", help="Record a measured result for a published brief.")
    outcome.add_argument("am_id", help="Opportunity id, e.g. AM-001.")
    outcome.add_argument("metric", help="Success-measure number from the brief, or a metric name.")
    outcome.add_argument("measured", help="Measured value, e.g. '4 min per claim'.")
    outcome.add_argument("--baseline", default="", help="Value before the change.")
    outcome.add_argument("--verdict", choices=("met", "partial", "missed"), help="Against target.")
    outcome.add_argument("--note", default="", help="Context: sample size, period, caveats.")
    workspace_arg(outcome)
    outcomes = sub.add_parser("outcomes", help="List measured outcomes with their ICE scores.")
    json_arg(outcomes)
    workspace_arg(outcomes)
