"""Shared fixtures — everything runs offline against the mock provider."""

from __future__ import annotations

from pathlib import Path

import pytest

from automation_miner.models import mock
from automation_miner.models.client import MinerModel
from automation_miner.models.config import load_config
from automation_miner.schemas import OpportunityDraft


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path / "ws"


@pytest.fixture
def mock_model(workspace: Path) -> MinerModel:
    return MinerModel(load_config(workspace), dry_run=True)


@pytest.fixture
def sample_draft() -> OpportunityDraft:
    return OpportunityDraft.model_validate(mock.call_json("drafter", "DraftBatch", "")["drafts"][0])
