"""Guarded real-provider smoke, critic-gate, and human-score evaluation.

The commands in this module are deliberately opt-in. They never run a provider
call without both ``--live`` and ``--privacy-approved``. Result files contain
metadata and aggregate measurements only; raw inputs, prompts, and provider
responses remain outside the repository and are never copied into a result.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from automation_miner.evaluation.live.common import (
    EvaluationError,
)
from automation_miner.evaluation.live.artifacts import (
    _smoke,
)
from automation_miner.evaluation.live.critic_gate import (
    _critic_gate,
)
from automation_miner.evaluation.live.ratings import (
    _score,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Guarded real-provider evaluation harness.")
    commands = parser.add_subparsers(dest="command", required=True)

    smoke = commands.add_parser("smoke", help="Run one bounded live mining invocation.")
    smoke_input = smoke.add_mutually_exclusive_group(required=True)
    smoke_input.add_argument("--idea")
    smoke_input.add_argument("--file", type=Path)
    smoke_input.add_argument("--kb", type=Path)
    smoke.add_argument("--workspace", type=Path, required=True)
    smoke.add_argument("--profile", default="live_flash")
    smoke.add_argument("--constraints", default="")
    smoke.add_argument("--iterations", type=int, default=1)
    smoke.add_argument("--mode", choices=("auto", "operational", "strategy"), default="auto")
    smoke.add_argument("--result", type=Path, required=True)
    smoke.add_argument("--live", action="store_true")
    smoke.add_argument("--privacy-approved", action="store_true")
    smoke.add_argument("--force", action="store_true")

    gate = commands.add_parser("critic-gate", help="Evaluate the labelled critic corpus twice.")
    gate.add_argument("--workspace", type=Path, required=True)
    gate.add_argument("--profile", default="live_flash")
    gate.add_argument("--strong-profile", required=True)
    gate.add_argument("--corpus", type=Path, required=True)
    gate.add_argument("--result", type=Path, required=True)
    gate.add_argument("--live", action="store_true")
    gate.add_argument("--privacy-approved", action="store_true")
    gate.add_argument("--force", action="store_true")

    score = commands.add_parser("score", help="Summarize two blinded human rating sheets.")
    score.add_argument("--ratings", type=Path, required=True)
    score.add_argument("--result", type=Path, required=True)
    score.add_argument("--force", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "smoke":
            return _smoke(args)
        if args.command == "critic-gate":
            return _critic_gate(args)
        return _score(args)
    except EvaluationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
