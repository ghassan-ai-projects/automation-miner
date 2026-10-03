"""Shared base model, enums, and layer constants for every artifact contract."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class ArtifactModel(BaseModel):
    """Strict base contract for model responses and persisted artifacts."""

    model_config = ConfigDict(extra="forbid")


class Layer(StrEnum):
    """The five orthogonal analysis layers from the spec."""

    DOCUMENT = "document"
    COMMUNICATION = "communication"
    DECISION = "decision"
    MONITORING = "monitoring"
    KNOWLEDGE = "knowledge"


class AnalysisMode(StrEnum):
    """How evidence should be interpreted before opportunities are generated."""

    AUTO = "auto"
    OPERATIONAL = "operational"
    STRATEGY = "strategy"


LAYER_ORDER: list[Layer] = list(Layer)

LAYER_TITLES: dict[Layer, str] = {
    Layer.DOCUMENT: "Document & Data Processing",
    Layer.COMMUNICATION: "Communication & Coordination",
    Layer.DECISION: "Decision & Approval",
    Layer.MONITORING: "Monitoring & Alerting",
    Layer.KNOWLEDGE: "Knowledge & Training",
}


class Level(StrEnum):
    """Low/Medium/High estimate levels (effort, impact, risk, pain)."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

    @property
    def rank(self) -> int:
        return {Level.LOW: 1, Level.MEDIUM: 2, Level.HIGH: 3}[self]


class OppStatus(StrEnum):
    """Lifecycle status of an opportunity brief."""

    IDENTIFIED = "identified"
    EVALUATING = "evaluating"
    DESIGNING = "designing"
    IMPLEMENTING = "implementing"
    LIVE = "live"
    DEPRECATED = "deprecated"


class Tier(StrEnum):
    """ICE band, so a score is legible without remembering the 1-125 scale."""

    VISION = "vision"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

    @classmethod
    def for_ice(cls, ice: int) -> Tier:
        if ice >= 80:
            return cls.VISION
        if ice >= 60:
            return cls.HIGH
        if ice >= 40:
            return cls.MEDIUM
        return cls.LOW

    @property
    def label(self) -> str:
        return {
            Tier.VISION: "Vision (ICE 80+)",
            Tier.HIGH: "High (ICE 60-79)",
            Tier.MEDIUM: "Medium (ICE 40-59)",
            Tier.LOW: "Low (ICE <40)",
        }[self]

    @property
    def rank(self) -> int:
        return {Tier.VISION: 4, Tier.HIGH: 3, Tier.MEDIUM: 2, Tier.LOW: 1}[self]


class Eligibility(StrEnum):
    """Whether an opportunity reached publication or was filtered by policy.

    Filtered opportunities are retained rather than deleted: they were drafted,
    critiqued, refined and scored, so discarding them silently hides work the
    operator paid for.
    """

    PUBLISHED = "published"
    FILTERED = "filtered"
