"""Ingest normalization: idea, file, KB folder, budget digest path."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from automation_miner.ingest import (
    TOKEN_BUDGET_CHARS,
    ingest_file,
    ingest_idea,
    ingest_kb,
    slugify,
)
from automation_miner.models.client import MinerModel


def test_slugify() -> None:
    assert slugify("German Healthcare System") == "german-healthcare-system"
    assert slugify("Carrier Bidding & Negotiation (eShop)") == "carrier-bidding-negotiation"


def test_ingest_idea() -> None:
    packet = ingest_idea("German healthcare back office", "budget:low")
    assert packet.source_kind == "idea"
    assert packet.domain == "German healthcare back office"
    assert packet.constraints == "budget:low"
    assert packet.domain_slug == "german-healthcare-back-office"


def test_ingest_file_markdown(tmp_path: Path) -> None:
    f = tmp_path / "brief.md"
    f.write_text("# Domain brief\n\nLots of manual work.", encoding="utf-8")
    packet = ingest_file(f)
    assert packet.source_kind == "file"
    assert "manual work" in packet.content
    assert packet.files == [str(f)]


def test_ingest_file_json_and_yaml(tmp_path: Path) -> None:
    jf = tmp_path / "data.json"
    jf.write_text(json.dumps({"systems": ["ERP", "CRM"]}), encoding="utf-8")
    assert "ERP" in ingest_file(jf).content

    yf = tmp_path / "data.yaml"
    yf.write_text("team: 3\nbudget: low\n", encoding="utf-8")
    packet = ingest_file(yf)
    assert '"team": 3' in packet.content


def test_ingest_file_rejects_unsupported(tmp_path: Path) -> None:
    f = tmp_path / "x.exe"
    f.write_text("nope", encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported"):
        ingest_file(f)


def test_ingest_kb_under_budget(tmp_path: Path) -> None:
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "a.md").write_text("alpha " * 50, encoding="utf-8")
    (kb / "b.txt").write_text("beta " * 50, encoding="utf-8")
    packet = ingest_kb(kb)
    assert packet.source_kind == "kb"
    assert not packet.digested
    assert "alpha" in packet.content and "beta" in packet.content
    assert len(packet.files) == 2


def test_ingest_kb_over_budget_digests(tmp_path: Path, mock_model: MinerModel) -> None:
    kb = tmp_path / "kb"
    kb.mkdir()
    for i in range(5):
        (kb / f"big{i}.md").write_text("word " * TOKEN_BUDGET_CHARS, encoding="utf-8")
    packet = ingest_kb(kb, model=mock_model)
    assert packet.digested
    assert "Digest of" in packet.content
    assert len(packet.content) <= TOKEN_BUDGET_CHARS + 200


def test_ingest_kb_empty_raises(tmp_path: Path) -> None:
    kb = tmp_path / "kb"
    kb.mkdir()
    with pytest.raises(ValueError, match="No supported files"):
        ingest_kb(kb)


def test_truncation_marks_packet() -> None:
    packet = ingest_idea("x" * (TOKEN_BUDGET_CHARS + 10))
    assert packet.truncated
    assert len(packet.content) <= TOKEN_BUDGET_CHARS + 100
