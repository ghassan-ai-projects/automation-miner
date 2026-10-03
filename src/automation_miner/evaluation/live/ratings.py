"""Blinded human-rating analysis: agreement and threshold checks."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from automation_miner.evaluation.live.common import (
    EvaluationError,
    _mapping,
    _load_object,
    _write_result,
    _now,
    _require_external_path,
    RATING_DIMENSIONS,
    EPISTEMIC_STATUSES,
    MIN_WEIGHTED_KAPPA,
    IDENTITY_KEY_PARTS,
)


def _rating_value(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 10:
        raise EvaluationError(f"{label} must be an integer from 0 through 10")
    return value


def _is_placeholder(value: str) -> bool:
    stripped = value.strip().casefold()
    return stripped.startswith("<") and stripped.endswith(">")


def _contains_identity_key(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            any(part in str(key).casefold() for part in IDENTITY_KEY_PARTS) for key in value
        ) or any(
            _contains_identity_key(child) for child in value.values()
        )
    if isinstance(value, list):
        return any(_contains_identity_key(child) for child in value)
    return False


def weighted_cohens_kappa(first: Sequence[int], second: Sequence[int]) -> float:
    """Return quadratic-weighted Cohen's kappa for the 0–10 rating scale."""
    if len(first) != len(second) or not first:
        raise EvaluationError("kappa requires paired, non-empty ratings")
    size = 11
    observed = [[0.0] * size for _ in range(size)]
    for left, right in zip(first, second):
        observed[left][right] += 1.0 / len(first)
    left_hist = [sum(row) for row in observed]
    right_hist = [sum(observed[row][column] for row in range(size)) for column in range(size)]
    expected = [[left_hist[row] * right_hist[column] for column in range(size)] for row in range(size)]
    denominator = 0.0
    numerator = 0.0
    for row in range(size):
        for column in range(size):
            weight = ((row - column) / 10) ** 2
            numerator += weight * observed[row][column]
            denominator += weight * expected[row][column]
    return round(1.0 - numerator / denominator, 4) if denominator else 1.0


def _check_payload(payload: Mapping[str, Any]) -> list[Any]:
    """Payload-level rules: blinded, commit-pinned, anonymous, and large enough."""
    if payload.get("blinded") is not True:
        raise EvaluationError("ratings must declare blinded=true")
    commit = payload.get("commit")
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-fA-F]{7,40}", commit):
        raise EvaluationError("ratings must include the evaluated commit")
    if _contains_identity_key(payload):
        raise EvaluationError("ratings must not contain provider or model identity fields")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or len(raw_items) < 10:
        raise EvaluationError("ratings require at least 10 reviewable opportunities")
    return raw_items


def _check_claim(assessment: object, where: str) -> None:
    claim = _mapping(assessment, f"{where}.claim_assessment")
    claim_id = claim.get("claim_id")
    if not isinstance(claim_id, str) or not claim_id or _is_placeholder(claim_id):
        raise EvaluationError(f"{where}.claim_id is required")
    refs = claim.get("evidence_refs")
    if not isinstance(refs, list) or not refs or any(
        not isinstance(ref, str) or not ref or _is_placeholder(ref) for ref in refs
    ):
        raise EvaluationError(f"{where}.evidence_refs is required")
    if claim.get("epistemic_status") not in EPISTEMIC_STATUSES:
        raise EvaluationError(f"{where}.epistemic_status is invalid")


def _check_rater(rater: Mapping[str, Any], where: str) -> None:
    if rater.get("publication_decision") not in {"publish", "filter", "abstain"}:
        raise EvaluationError(f"{where}.publication_decision is invalid")
    if not isinstance(rater.get("critical_unsupported_current_state_claim"), bool):
        raise EvaluationError(f"{where}.critical_unsupported_current_state_claim must be boolean")
    assessments = rater.get("claim_assessments")
    if not isinstance(assessments, list) or not assessments:
        raise EvaluationError(f"{where}.claim_assessments is required")
    for assessment in assessments:
        _check_claim(assessment, where)


@dataclass
class _Tally:
    """Everything the score card needs, accumulated item by item."""

    scores: dict[str, list[tuple[int, int]]] = field(
        default_factory=lambda: {dimension: [] for dimension in RATING_DIMENSIONS}
    )
    disagreements: list[str] = field(default_factory=list)
    publication_disagreements: list[str] = field(default_factory=list)
    critical_claims: list[str] = field(default_factory=list)
    abstentions: list[str] = field(default_factory=list)
    domains: set[str] = field(default_factory=set)
    seen: set[str] = field(default_factory=set)


def _item_identity(item: Mapping[str, Any], tally: _Tally) -> str:
    item_id = item.get("id")
    if not isinstance(item_id, str) or not item_id or item_id in tally.seen:
        raise EvaluationError("rating item ids must be unique non-empty strings")
    tally.seen.add(item_id)
    domain = item.get("domain")
    if not isinstance(domain, str) or not domain.strip():
        raise EvaluationError(f"{item_id}.domain is required")
    tally.domains.add(domain.strip())
    return item_id


def _tally_scores(
    item_id: str, first: Mapping[str, Any], second: Mapping[str, Any], tally: _Tally
) -> None:
    max_difference = 0
    for dimension in RATING_DIMENSIONS:
        left = _rating_value(first.get(dimension), f"{item_id}.rater_a.{dimension}")
        right = _rating_value(second.get(dimension), f"{item_id}.rater_b.{dimension}")
        tally.scores[dimension].append((left, right))
        max_difference = max(max_difference, abs(left - right))
    if max_difference > 2:
        tally.disagreements.append(item_id)


def _tally_item(raw: object, tally: _Tally) -> None:
    item = _mapping(raw, "rating item")
    item_id = _item_identity(item, tally)
    first = _mapping(item.get("rater_a"), f"{item_id}.rater_a")
    second = _mapping(item.get("rater_b"), f"{item_id}.rater_b")
    _tally_scores(item_id, first, second, tally)
    _check_rater(first, f"{item_id}.rater_a")
    _check_rater(second, f"{item_id}.rater_b")
    decisions = {first["publication_decision"], second["publication_decision"]}
    if len(decisions) > 1:
        tally.publication_disagreements.append(item_id)
    if "abstain" in decisions:
        tally.abstentions.append(item_id)
    key = "critical_unsupported_current_state_claim"
    if first.get(key) is True or second.get(key) is True:
        tally.critical_claims.append(item_id)


def _per_dimension(scores: dict[str, list[tuple[int, int]]]) -> tuple[dict[str, Any], float]:
    """Mean and weighted kappa per dimension, plus the overall mean of every score."""
    per_dimension: dict[str, dict[str, Any]] = {}
    all_scores: list[int] = []
    for dimension, pairs in scores.items():
        left_scores = [pair[0] for pair in pairs]
        right_scores = [pair[1] for pair in pairs]
        all_scores.extend(left_scores + right_scores)
        per_dimension[dimension] = {
            "mean": round(sum(left_scores + right_scores) / (2 * len(pairs)), 3),
            "weighted_cohens_kappa": weighted_cohens_kappa(left_scores, right_scores),
        }
    return per_dimension, round(sum(all_scores) / len(all_scores), 3)


# Predeclared minimum mean per dimension; the overall mean must reach 6.0 too.
_MIN_MEANS = {"groundedness": 7.0, "honesty": 7.0, "actionability": 6.0, "specificity": 6.0}


def summarize_ratings(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate two blinded raters and calculate the predeclared score card."""
    raw_items = _check_payload(payload)
    tally = _Tally()
    for raw in raw_items:
        _tally_item(raw, tally)
    if not 2 <= len(tally.domains) <= 3:
        raise EvaluationError("ratings must cover two or three domains")
    per_dimension, overall = _per_dimension(tally.scores)
    adjudication_required = sorted(
        set(tally.disagreements + tally.publication_disagreements + tally.abstentions)
    )
    agreement_pass = all(
        item["weighted_cohens_kappa"] >= MIN_WEIGHTED_KAPPA for item in per_dimension.values()
    )
    means_pass = all(per_dimension[name]["mean"] >= floor for name, floor in _MIN_MEANS.items())
    blockers = tally.critical_claims or adjudication_required or not agreement_pass
    threshold_pass = means_pass and overall >= 6.0 and not blockers
    return {
        "items": len(raw_items), "domains": sorted(tally.domains), "per_dimension": per_dimension,
        "minimum_weighted_kappa": MIN_WEIGHTED_KAPPA, "agreement_pass": agreement_pass,
        "overall_mean": overall, "disagreements_over_2": tally.disagreements,
        "publication_decision_disagreements": tally.publication_disagreements,
        "critical_unsupported_current_state_claims": tally.critical_claims,
        "adjudication_required": adjudication_required, "thresholds_pass": threshold_pass,
    }


def _score(args: argparse.Namespace) -> int:
    ratings_path = _require_external_path(args.ratings, "ratings")
    result_path = _require_external_path(args.result, "result")
    payload = _load_object(ratings_path)
    record: dict[str, Any] = {
        "kind": "human_rating_summary",
        "version": "human-rating-summary-v1",
        "generated_at": _now(),
        "commit": str(payload.get("commit", "")),
        "ratings_version": str(payload.get("version", "")),
        "privacy": {"raw_ratings_saved": False},
        "summary": summarize_ratings(payload),
    }
    _write_result(result_path, record, args.force)
    print(json.dumps(record, indent=2, ensure_ascii=False))
    return 0 if record["summary"]["thresholds_pass"] else 1
