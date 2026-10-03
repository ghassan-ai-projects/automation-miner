"""Run the quality suite against a real provider and grade it against the bar.

Usage:

    uv run python scripts/quality_suite.py --out /tmp/am-quality/iter-1 \
        --config examples/miner.toml [--cases claims,strategy,oneliner] [--no-judge]

Each case runs in its own workspace (so prior-idea memory cannot leak across
cases), is evaluated with ``automation_miner.evaluation``, and is graded
against the thresholds in ``docs/quality/00-QUALITY-BAR.md``. The aggregate
verdict is written to ``<out>/quality-report.{json,md}``.

This spends real provider credit. It needs the API keys named in the config.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from automation_miner.evaluation import evaluate_run
from automation_miner.evaluation.schemas import RunEvaluation
from automation_miner.graph.runner import run_mine
from automation_miner.models.client import MinerModel
from automation_miner.models.config import load_config

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_large_kb import make_large_kb  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Case:
    name: str
    kind: str
    value: str
    constraints: str = ""
    min_published: int = 3
    min_publication_rate: float = 0.0
    expected_mode: str = ""
    all_hypotheses: bool = False


CASES: dict[str, Case] = {
    "claims": Case(
        name="claims",
        kind="kb",
        value=str(ROOT / "examples" / "claims-intake"),
        constraints="compliance:heavy, team:5",
        min_published=4,
        min_publication_rate=0.6,
        expected_mode="operational",
    ),
    "strategy": Case(
        name="strategy",
        kind="file",
        value=str(ROOT / "examples" / "hospital-strategy-memo.md"),
        min_published=3,
        expected_mode="strategy",
    ),
    "oneliner": Case(
        name="oneliner",
        kind="idea",
        value="Independent veterinary clinics in the Netherlands",
        min_published=3,
        all_hypotheses=True,
    ),
    # The input of the first real run (DHL), kept as a regression case.
    "dhl": Case(
        name="dhl",
        kind="idea",
        value=(ROOT / "examples" / "dhl-germany-domain.md").read_text(encoding="utf-8"),
        min_published=4,
        min_publication_rate=0.6,
    ),
    # ~89k tokens of synthetic field-service records: exercises digestion and
    # per-stage evidence selection. Generated into the output directory.
    "large": Case(
        name="large",
        kind="kb",
        value="@large-kb",
        min_published=4,
        expected_mode="operational",
    ),
}

# The bar. Keep in sync with docs/quality/00-QUALITY-BAR.md.
BAR: dict[str, float] = {
    "max_minutes": 15.0,
    "max_lint_errors": 0,
    "min_judge_overall_mean": 4.0,
    "min_judge_dimension_mean": 3.5,
    "min_brief_overall": 3,
    "max_fabricated_facts_per_brief": 0.5,
    "min_portfolio_diversity": 4,
    "min_portfolio_coverage": 3,
}


@dataclass
class CaseResult:
    case: Case
    evaluation: RunEvaluation | None = None
    error: str = ""
    checks: dict[str, bool] = field(default_factory=dict)


def _key_usage(config_path: Path) -> float | None:
    """OpenRouter credit used so far by the configured key, if available."""
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key or "openrouter" not in config_path.read_text(encoding="utf-8"):
        return None
    try:
        response = httpx.get(
            "https://openrouter.ai/api/v1/key",
            headers={"Authorization": f"Bearer {key}"},
            timeout=30,
        )
        return float(response.json()["data"]["usage"])
    except Exception:
        return None


def _run_case(case: Case, out: Path, config_path: Path, judge: bool, iterations: int) -> CaseResult:
    workspace = out / case.name
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)
    shutil.copy(config_path, workspace / "miner.toml")
    value: Any = case.value
    if case.value == "@large-kb":
        value = make_large_kb(out / "_inputs" / "large-kb")
    kwargs: dict[str, Any] = {case.kind: Path(value) if case.kind != "idea" else value}
    result = CaseResult(case)
    try:
        state = run_mine(
            workspace_path=workspace,
            constraints=case.constraints,
            max_iterations=iterations,
            **kwargs,
        )
        run_dir = Path(state["run_dir"])
    except Exception as exc:  # noqa: BLE001 - a failed case is a measured result
        result.error = f"{type(exc).__name__}: {exc}"[:2_000]
        run_dir = Path(getattr(exc, "run_dir", "")) if getattr(exc, "run_dir", "") else None
        if run_dir is None:
            return result
    judge_model = MinerModel(load_config(workspace)) if judge else None
    try:
        if (run_dir / "summary.json").is_file():
            result.evaluation = evaluate_run(run_dir, workspace, judge_model, samples=2)
    finally:
        if judge_model is not None:
            judge_model.close()
    result.checks = _grade(case, result)
    return result


def _grade(case: Case, result: CaseResult) -> dict[str, bool]:
    ev = result.evaluation
    if ev is None:
        return {"completed": False}
    checks = {
        "completed": ev.status == "completed" and not result.error,
        "min_published": ev.published >= case.min_published,
        "publication_rate": ev.publication_rate >= case.min_publication_rate,
        "max_minutes": ev.duration_seconds / 60 <= BAR["max_minutes"],
        "lint_clean": ev.lint_errors <= BAR["max_lint_errors"],
    }
    if case.expected_mode:
        checks["mode"] = ev.analysis_mode == case.expected_mode
    if case.all_hypotheses:
        checks["hypothesis_framing"] = ev.discovery_hypotheses == ev.published
    if ev.briefs:
        dims = {k: v for k, v in ev.means.items() if k != "overall"}
        checks["judge_overall_mean"] = ev.means.get("overall", 0) >= BAR["min_judge_overall_mean"]
        checks["judge_dimension_means"] = min(dims.values()) >= BAR["min_judge_dimension_mean"]
        checks["judge_min_brief"] = ev.min_overall >= BAR["min_brief_overall"]
        checks["honesty"] = (
            ev.fabricated_facts / len(ev.briefs) <= BAR["max_fabricated_facts_per_brief"]
        )
    if ev.portfolio is not None:
        checks["portfolio_diversity"] = ev.portfolio.diversity >= BAR["min_portfolio_diversity"]
        checks["portfolio_coverage"] = ev.portfolio.coverage >= BAR["min_portfolio_coverage"]
    return checks


def _report(results: list[CaseResult], cost: float | None, label: str) -> tuple[dict[str, Any], str]:
    rows = []
    for r in results:
        ev = r.evaluation
        rows.append(
            {
                "case": r.case.name,
                "error": r.error,
                "checks": r.checks,
                "passed": bool(r.checks) and all(r.checks.values()),
                "run_id": ev.run_id if ev else "",
                "published": f"{ev.published}/{ev.total}" if ev else "",
                "minutes": round(ev.duration_seconds / 60, 1) if ev else None,
                "tokens": ev.total_tokens if ev else None,
                "lint_errors": ev.lint_errors if ev else None,
                "hedges": ev.hedges if ev else None,
                "means": ev.means if ev else {},
                "fabricated": ev.fabricated_facts if ev else None,
                "portfolio": ev.portfolio.model_dump() if ev and ev.portfolio else None,
            }
        )
    passed = all(row["passed"] for row in rows)
    overall = [row["means"].get("overall") for row in rows if row["means"]]
    data = {
        "label": label,
        "bar": BAR,
        "passed": passed,
        "cost_usd": round(cost, 4) if cost is not None else None,
        "judge_overall_mean": round(statistics.fmean(overall), 2) if overall else None,
        "cases": rows,
    }
    lines = [
        f"# Quality suite — {label}",
        "",
        f"**Verdict: {'PASS' if passed else 'FAIL'}** · cost "
        f"{'$' + format(cost, '.3f') if cost is not None else 'n/a'} · judge overall mean "
        f"{data['judge_overall_mean']}",
        "",
        "| Case | Published | Min | Lint err | Hedges | Overall | Fabricated | Diversity | Coverage | Failed checks |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        failed = [k for k, v in row["checks"].items() if not v] or (["error"] if row["error"] else [])
        portfolio = row["portfolio"] or {}
        lines.append(
            f"| {row['case']} | {row['published']} | {row['minutes']} | {row['lint_errors']} | "
            f"{row['hedges']} | {row['means'].get('overall', '—')} | {row['fabricated']} | "
            f"{portfolio.get('diversity', '—')} | {portfolio.get('coverage', '—')} | "
            f"{', '.join(failed) or '—'} |"
        )
    for row in rows:
        if row["error"]:
            lines += ["", f"**{row['case']} error:** {row['error']}"]
    return data, "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=ROOT / "examples" / "miner.toml")
    parser.add_argument("--cases", default=",".join(CASES))
    parser.add_argument("--label", default="")
    parser.add_argument("--iterations", type=int, default=2)
    parser.add_argument("--no-judge", action="store_true")
    args = parser.parse_args(argv)

    cases = [CASES[name.strip()] for name in args.cases.split(",") if name.strip()]
    args.out.mkdir(parents=True, exist_ok=True)
    before = _key_usage(args.config)
    started = time.time()
    with ThreadPoolExecutor(max_workers=len(cases)) as pool:
        results = list(
            pool.map(
                lambda case: _run_case(
                    case, args.out, args.config, not args.no_judge, args.iterations
                ),
                cases,
            )
        )
    after = _key_usage(args.config)
    cost = after - before if before is not None and after is not None else None
    data, markdown = _report(results, cost, args.label or args.out.name)
    data["wall_minutes"] = round((time.time() - started) / 60, 1)
    (args.out / "quality-report.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    (args.out / "quality-report.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    return 0 if data["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
