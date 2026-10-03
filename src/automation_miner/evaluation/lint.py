"""Deterministic brief lint: the reader-facing defects code can detect alone.

The first real run published a brief whose every bullet carried a provenance
hedge ("inferred from S2: '...'; X not explicitly stated"), whose steps were
numbered twice, and whose closing validation criterion was a garbled template
sentence. None of those needs a model to detect, and none of them should ever
reach a reader, so they are measured here as hard errors.
"""

from __future__ import annotations

import re
from pathlib import Path

from automation_miner.evaluation.schemas import BriefLint, LintFinding
from automation_miner.hygiene import find_hedges

_DOUBLE_NUMBER = re.compile(r"^\s*\d+[.)]\s+\d+[.)]\s", re.MULTILINE)
_NONE_IDENTIFIED = "(none identified)"
_REQUIRED_SECTIONS = ("Inputs", "Steps", "Outputs", "Human-in-the-Loop Points")
_FRONTMATTER_DOMAIN = re.compile(r'^domain:\s*"(.*)"\s*$', re.MULTILINE)
_SECTION = re.compile(r"^#{2,3} (.+)$", re.MULTILINE)
_BULLET = re.compile(r"^\s*(?:[-*]|\d+[.)])\s+(.*)$", re.MULTILINE)

MAX_BULLET_CHARS = 400
MAX_BRIEF_WORDS = 2_600


def _section_body(text: str, title: str) -> str | None:
    matches = list(_SECTION.finditer(text))
    for index, match in enumerate(matches):
        if match.group(1).strip() == title:
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            return text[match.end() : end]
    return None


def _error(code: str, excerpt: str) -> LintFinding:
    return LintFinding(code=code, severity="error", excerpt=excerpt)


def _prose_findings(body: str) -> list[LintFinding]:
    """Evidence commentary in prose; the Evidence section may list ids."""
    prose = body.split("\n## Evidence\n", 1)[0]
    findings = [_error(f"hedge:{h.code}", h.excerpt) for h in find_hedges(prose)]
    findings += [_error("double-numbering", m.group(0).strip()) for m in _DOUBLE_NUMBER.finditer(body)]
    if re.search(r"Actual time saved vs\. the .{0,200}? projected above", body):
        findings.append(_error("garbled-validation-criterion", "Validation criteria"))
    return findings


def _structure_findings(text: str, body: str) -> list[LintFinding]:
    findings = []
    for section in _REQUIRED_SECTIONS:
        section_text = _section_body(body, section)
        if section_text is None:
            findings.append(_error("missing-section", section))
        elif _NONE_IDENTIFIED in section_text:
            findings.append(_error("empty-section", section))
    domain = _FRONTMATTER_DOMAIN.search(text)
    if domain and re.search(r"[:;,\-—–]\s*$", domain.group(1)):
        findings.append(_error("domain-trailing-punctuation", domain.group(1)))
    return findings


def _size_findings(body: str, words: int) -> list[LintFinding]:
    findings = [
        LintFinding(code="bloated-bullet", severity="warning", excerpt=bullet[:120] + "…")
        for bullet in _BULLET.findall(body)
        if len(bullet) > MAX_BULLET_CHARS
    ]
    if words > MAX_BRIEF_WORDS:
        findings.append(
            LintFinding(code="overlong-brief", severity="warning", excerpt=f"{words} words")
        )
    return findings


def lint_brief(text: str, name: str = "") -> BriefLint:
    """Lint one rendered brief. Errors must be zero for a publishable brief."""
    body = text.split("\n---\n", 1)[-1] if text.startswith("---") else text
    words = len(body.split())
    findings = (
        _prose_findings(body) + _structure_findings(text, body) + _size_findings(body, words)
    )
    hedges = sum(1 for f in findings if f.code.startswith("hedge:"))
    return BriefLint(
        brief=name,
        words=words,
        hedge_count=hedges,
        hedges_per_1k_words=round(hedges * 1000 / words, 2) if words else 0.0,
        errors=sum(1 for f in findings if f.severity == "error"),
        warnings=sum(1 for f in findings if f.severity == "warning"),
        findings=findings,
    )


def lint_paths(paths: list[Path]) -> list[BriefLint]:
    return [lint_brief(path.read_text(encoding="utf-8"), path.name) for path in paths]
