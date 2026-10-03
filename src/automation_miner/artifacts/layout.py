"""The on-disk layout of one run — the only place artifact paths are spelled.

A run directory separates **results** (what a consumer reads) from **trace**
(how the pipeline got there)::

    runs/<run-id>/
      run.json              manifest: status, input, models, budget, usage, timings
      opportunities.json    the result: every opportunity, final score, eligibility
      summary.json          compact agent-facing view of the result
      report.md             human report
      evaluation.json/.md   optional quality grade (``automation-miner evaluate``)
      error.json            only on failure
      publication/          staged briefs and the crash-recovery journal.json
      trace/
        context.json        evidence index the briefs cite (S-ids)
        input_assessment.json, domain_map.json, candidate_portfolio.json
        pain_ledger.json    pains ranked by size, and which candidate covers each
        layers/<layer>.json
        drafts/<candidate>.json         first draft per planned candidate
        critique/AM-XXX.v<n>.json       every critique round with its draft
        run-log.md                      phase-by-phase human run log

Layout 1 (before October 2026) kept trace files at the top level and also
wrote ``scores.json`` and ``ranked.json``, two full copies of the portfolio.
Readers fall back to the layout-1 location so old runs stay readable.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

LAYOUT_VERSION = 2


@dataclass(frozen=True)
class RunLayout:
    root: Path

    # -- results ---------------------------------------------------------------

    @property
    def manifest(self) -> Path:
        return self.root / "run.json"

    @property
    def opportunities(self) -> Path:
        return self.root / "opportunities.json"

    @property
    def summary(self) -> Path:
        return self.root / "summary.json"

    @property
    def report(self) -> Path:
        return self.root / "report.md"

    @property
    def one_pager(self) -> Path:
        return self.root / "one-pager.html"

    @property
    def evaluation(self) -> Path:
        return self.root / "evaluation.json"

    @property
    def evaluation_md(self) -> Path:
        return self.root / "evaluation.md"

    @property
    def error(self) -> Path:
        return self.root / "error.json"

    @property
    def publication(self) -> Path:
        return self.root / "publication"

    @property
    def journal(self) -> Path:
        """Crash-recovery journal for the publication transaction."""
        return self._readable(self.publication / "journal.json", legacy_name="publication.json")

    # -- trace -------------------------------------------------------------------

    @property
    def trace(self) -> Path:
        return self.root / "trace"

    @property
    def context(self) -> Path:
        return self._readable(self.trace / "context.json")

    @property
    def input_assessment(self) -> Path:
        return self._readable(self.trace / "input_assessment.json")

    @property
    def domain_map(self) -> Path:
        return self._readable(self.trace / "domain_map.json")

    @property
    def candidate_portfolio(self) -> Path:
        return self._readable(self.trace / "candidate_portfolio.json")

    @property
    def pain_ledger(self) -> Path:
        return self.trace / "pain_ledger.json"

    @property
    def layers(self) -> Path:
        return self.trace / "layers"

    @property
    def drafts(self) -> Path:
        return self.trace / "drafts"

    @property
    def critique(self) -> Path:
        return self.trace / "critique"

    @property
    def run_log(self) -> Path:
        return self.trace / "run-log.md"

    def layer(self, name: str) -> Path:
        return self.layers / f"{name}.json"

    def candidate_draft(self, slug: str) -> Path:
        return self.drafts / f"{slug}.json"

    def critique_round(self, am_id: str, version: int) -> Path:
        return self.critique / f"{am_id}.v{version}.json"

    def _readable(self, path: Path, legacy_name: str = "") -> Path:
        """Layout-2 path, or the layout-1 top-level file when only that exists."""
        legacy = self.root / (legacy_name or path.name)
        return legacy if not path.exists() and legacy.exists() else path
