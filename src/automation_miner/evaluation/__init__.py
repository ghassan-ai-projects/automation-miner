"""Measure the quality of a completed run — the product's own quality bar.

Two instruments, deliberately separated:

* **Lint** is deterministic and free. It catches reader-facing defects code can
  prove: provenance hedging inside prose, double numbering, empty sections,
  garbled template sentences.
* **The judge** is an independent model (configure the ``judge`` role with a
  different, stronger model family than the generator). It grades each
  published brief the way a process owner would read it, and the portfolio as a
  whole. It is a calibrated proxy for human review, not a substitute for it.

Results are written to ``evaluation.json`` and ``evaluation.md`` in the run
directory, next to the artifacts they grade.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from automation_miner.artifacts.layout import RunLayout
from automation_miner.artifacts.workspace import read_json, write_json, write_text
from automation_miner.evaluation.judge import judge_brief, judge_portfolio
from automation_miner.evaluation.lint import lint_brief
from automation_miner.evaluation.render import render_evaluation
from automation_miner.evaluation.schemas import (
    JUDGE_DIMENSIONS,
    JudgedBrief,
    PortfolioJudgement,
    RunEvaluation,
)
from automation_miner.models.client import MinerModel

__all__ = ["evaluate_run", "render_evaluation"]


def _published_briefs(run_dir: Path, workspace_root: Path) -> list[tuple[dict[str, Any], Path]]:
    summary = read_json(run_dir / "summary.json")
    briefs: list[tuple[dict[str, Any], Path]] = []
    for entry in summary.get("opportunities", []):
        if entry.get("eligibility") != "published" or not entry.get("brief_path"):
            continue
        path = Path(entry["brief_path"])
        if not path.is_absolute():
            path = workspace_root / path
        if path.is_file():
            briefs.append((entry, path))
    return briefs


@dataclass
class _RunInputs:
    """What the judge needs from one run, read once."""

    manifest: dict[str, Any]
    summary: dict[str, Any]
    briefs: list[tuple[dict[str, Any], Path]]
    texts: dict[str, str]


def _inputs(run_dir: Path, workspace_root: Path) -> _RunInputs:
    briefs = _published_briefs(run_dir, workspace_root)
    texts = {entry["am_id"]: path.read_text(encoding="utf-8") for entry, path in briefs}
    return _RunInputs(
        read_json(run_dir / "run.json"), read_json(run_dir / "summary.json"), briefs, texts
    )


def _base(run_dir: Path, run: _RunInputs) -> RunEvaluation:
    """Lint every published brief; record the run's shape and cost."""
    stats, usage = run.summary.get("stats", {}), run.summary.get("usage", {})
    lints = [lint_brief(run.texts[entry["am_id"]], path.name) for entry, path in run.briefs]
    total, published = int(stats.get("total", 0)), int(stats.get("published", 0))
    hypotheses = [e for e, _ in run.briefs if e.get("artifact_type") == "discovery_hypothesis"]
    return RunEvaluation(
        run_id=run_dir.name, status=str(run.manifest.get("status", "")),
        analysis_mode=str(run.manifest.get("analysis_mode", "")), total=total,
        published=published, publication_rate=round(published / total, 3) if total else 0.0,
        discovery_hypotheses=len(hypotheses),
        duration_seconds=float(run.summary.get("duration_seconds", 0.0)),
        total_tokens=int(usage.get("total_tokens", 0)), model_calls=int(usage.get("calls", 0)),
        lint=lints, lint_errors=sum(lint.errors for lint in lints),
        hedges=sum(lint.hedge_count for lint in lints),
    )


def _judged(
    model: MinerModel, run_dir: Path, run: _RunInputs, workers: int, samples: int
) -> tuple[list[JudgedBrief], PortfolioJudgement]:
    evidence = str(read_json(RunLayout(run_dir).context).get("overview", ""))
    domain, mode = str(run.manifest.get("domain", "")), str(run.manifest.get("analysis_mode", ""))
    constraints = str(run.manifest.get("constraints", ""))

    def judge(item: tuple[dict[str, Any], Path]) -> JudgedBrief:
        entry, _ = item
        text = run.texts[entry["am_id"]]
        verdict = judge_brief(model, text, evidence, domain, constraints, mode, samples=samples)
        return JudgedBrief(am_id=entry["am_id"], title=entry["title"], judgement=verdict)

    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(run.briefs)))) as pool:
        judged = list(pool.map(judge, run.briefs))
    filtered = [
        str(e.get("title", ""))
        for e in run.summary.get("opportunities", [])
        if e.get("eligibility") != "published"
    ]
    briefs = [(entry, run.texts[entry["am_id"]]) for entry, _ in run.briefs]
    return judged, judge_portfolio(model, briefs, filtered, evidence, domain, mode)


def evaluate_run(
    run_dir: Path, workspace_root: Path, model: MinerModel | None = None, *,
    workers: int = 4, samples: int = 1,
) -> RunEvaluation:
    """Lint every published brief and, when a model is given, judge them."""
    run = _inputs(run_dir, workspace_root)
    evaluation = _base(run_dir, run)
    if model is not None and run.briefs:
        judged, portfolio = _judged(model, run_dir, run, workers, samples)
        means = {
            dim: round(statistics.fmean(getattr(j.judgement, dim) for j in judged), 2)
            for dim in (*JUDGE_DIMENSIONS, "overall")
        }
        route = model.config.resolve("judge", dry_run=model.dry_run)
        evaluation = evaluation.model_copy(
            update={
                "judge_model": f"{route.provider}/{route.model}", "briefs": judged,
                "portfolio": portfolio, "means": means,
                "fabricated_facts": sum(len(j.judgement.fabricated_facts) for j in judged),
                "min_overall": min(j.judgement.overall for j in judged),
            }
        )
    write_json(run_dir / "evaluation.json", evaluation)
    write_text(run_dir / "evaluation.md", render_evaluation(evaluation))
    return evaluation


__all__ = ["evaluate_run", "render_evaluation"]
