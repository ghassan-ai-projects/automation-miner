"""Lifecycle contracts: what happened to a brief after it was published."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from automation_miner.schemas.base import ArtifactModel, OppStatus

Verdict = Literal["met", "partial", "missed"]


class LifecycleEvent(ArtifactModel):
    """One status change or one measured outcome, appended and never edited."""

    am_id: str = Field(pattern=r"^AM-\d+$")
    at: str
    kind: Literal["status", "outcome"]
    status: OppStatus | None = None
    previous: OppStatus | None = None
    metric: str = ""
    baseline: str = ""
    measured: str = ""
    verdict: Verdict | None = None
    note: str = ""


class LifecycleLedger(ArtifactModel):
    """Every lifecycle event in a workspace, in the order it was recorded."""

    v: int = 1
    events: list[LifecycleEvent] = Field(default_factory=list)

    def for_id(self, am_id: str) -> list[LifecycleEvent]:
        return [event for event in self.events if event.am_id == am_id]
