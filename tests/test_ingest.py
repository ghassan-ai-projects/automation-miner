"""Ingest: idea, file, KB folder, error isolation, budgets, digest targets."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import automation_miner.ingest.packet as ingest_module
from automation_miner.context import ContextBudget, estimate_tokens
from automation_miner.ingest import MAX_SLUG_CHARS, ingest_file, ingest_idea, ingest_kb, slugify
from automation_miner.models.client import MinerModel

SMALL = ContextBudget(evidence_tokens=400, chunk_tokens=120, digest_chunk_tokens=200)


def test_slugify() -> None:
    assert slugify("German Healthcare System") == "german-healthcare-system"
    assert slugify("Carrier Bidding & Negotiation (eShop)") == "carrier-bidding-negotiation"


def test_ingest_idea() -> None:
    packet = ingest_idea("German healthcare back office", "budget:low")
    assert packet.source_kind == "idea"
    assert packet.domain == "German healthcare back office"
    assert packet.constraints == "budget:low"
    assert packet.domain_slug == "german-healthcare-back-office"
    assert len(packet.chunks) == 1
    assert packet.chunks[0].id == "S1"
    assert "German healthcare" in packet.overview


def test_ingest_idea_rejects_empty_and_bounds_slug() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        ingest_idea("  \n")
    assert len(ingest_idea("x" * 10_000).domain_slug) == MAX_SLUG_CHARS


def test_ingest_file_markdown_produces_heading_locators(tmp_path: Path) -> None:
    path = tmp_path / "brief.md"
    path.write_text(
        "# Domain brief\n\nLots of manual work.\n\n## Intake\n\n400 claims/day.\n",
        encoding="utf-8",
    )
    packet = ingest_file(path)
    assert packet.source_kind == "file"
    assert packet.files == [str(path)]
    assert any("Intake" in chunk.locator for chunk in packet.chunks)
    assert "400 claims/day" in packet.overview


def test_ingest_file_reads_pdf(tmp_path: Path) -> None:
    pytest.importorskip("pypdf")
    from pdf_fixtures import make_pdf

    path = tmp_path / "regulation.pdf"
    path.write_bytes(make_pdf(["Audit trail retained for 10 years."]))
    packet = ingest_file(path)
    assert "Audit trail" in packet.overview
    assert packet.chunks[0].locator == "p.1"


def test_ingest_file_rejects_unreadable(tmp_path: Path) -> None:
    path = tmp_path / "logo.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(range(256)))
    with pytest.raises(ValueError, match="Cannot read"):
        ingest_file(path)


def test_ingest_file_rejects_missing_path(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="does not exist"):
        ingest_file(tmp_path / "missing.md")


def test_ingest_kb_under_budget_keeps_everything(tmp_path: Path) -> None:
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "a.md").write_text("alpha " * 50, encoding="utf-8")
    (kb / "b.txt").write_text("beta " * 50, encoding="utf-8")
    packet = ingest_kb(kb)
    assert packet.source_kind == "kb"
    assert not packet.stats.digested
    assert "alpha" in packet.overview and "beta" in packet.overview
    assert packet.stats.included_files == 2
    # Only trailing whitespace is lost when nothing needs compressing.
    assert packet.stats.retention_pct >= 99.0


def test_malformed_json_does_not_abort_the_folder(tmp_path: Path) -> None:
    """One truncated export used to raise JSONDecodeError out of ingest_kb."""
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "good.md").write_text("Manual reconciliation takes 4 hours.", encoding="utf-8")
    (kb / "broken.json").write_text('{"systems": ["SAP",  // truncated\n', encoding="utf-8")
    packet = ingest_kb(kb)
    assert packet.stats.included_files == 2
    assert "SAP" in packet.overview
    assert "reconciliation" in packet.overview


def test_unreadable_files_are_skipped_with_reasons(tmp_path: Path) -> None:
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "good.md").write_text("Useful evidence about claims.", encoding="utf-8")
    (kb / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(range(256)))
    (kb / "empty.md").write_text("", encoding="utf-8")

    packet = ingest_kb(kb)
    assert packet.stats.included_files == 1
    assert packet.stats.skipped_files == 2
    reasons = {Path(s.path).name: s.reason for s in packet.skipped}
    assert "binary" in reasons["logo.png"]
    assert "empty" in reasons["empty.md"]


def test_latin1_file_does_not_break_ingestion(tmp_path: Path) -> None:
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "legacy.txt").write_bytes(
        "Rückstände: 1.240 Fälle offen. Prüfung erfolgt manuell.".encode("latin-1")
    )
    packet = ingest_kb(kb)
    assert "Rückstände" in packet.overview
    assert packet.stats.skipped_files == 0


def test_oversized_file_is_skipped_not_fatal(tmp_path: Path) -> None:
    from automation_miner.readers import build_registry

    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "ok.md").write_text("small", encoding="utf-8")
    (kb / "huge.txt").write_text("x" * 5_000, encoding="utf-8")
    packet = ingest_kb(kb, registry=build_registry({"max_file_bytes": 1_000}))
    assert packet.stats.included_files == 1
    assert any("max_file_bytes" in s.reason for s in packet.skipped)


def test_kb_with_no_readable_file_raises(tmp_path: Path) -> None:
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(range(256)))
    with pytest.raises(ValueError, match="No readable files"):
        ingest_kb(kb)


def test_ingest_kb_empty_folder_raises(tmp_path: Path) -> None:
    kb = tmp_path / "kb"
    kb.mkdir()
    with pytest.raises(ValueError, match="No files found"):
        ingest_kb(kb)


def test_ingest_kb_rejects_missing_folder(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="does not exist"):
        ingest_kb(tmp_path / "missing")


def test_symlink_escaping_the_kb_is_refused(tmp_path: Path) -> None:
    outside = tmp_path / "outside.md"
    outside.write_text("secret", encoding="utf-8")
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "real.md").write_text("evidence", encoding="utf-8")
    (kb / "escape.md").symlink_to(outside)

    packet = ingest_kb(kb)
    assert "secret" not in packet.overview
    assert any("outside the knowledge base" in s.reason for s in packet.skipped)


# ---------------------------------------------------------------------------
# Budget and digest behaviour
# ---------------------------------------------------------------------------


def test_over_budget_kb_digests_toward_the_budget(
    tmp_path: Path, mock_model: MinerModel
) -> None:
    """The old digester ignored its budget and returned ~4% of it."""
    kb = tmp_path / "kb"
    kb.mkdir()
    for i in range(6):
        (kb / f"doc{i}.md").write_text(
            f"# Doc {i}\n\n" + f"Team {i} processes 400 claims/day in SAP. " * 60,
            encoding="utf-8",
        )
    packet = ingest_kb(kb, model=mock_model, budget=SMALL)

    assert packet.stats.digested
    assert packet.stats.evidence_tokens <= SMALL.evidence_tokens
    # The point of the fix: the digest must actually use the allowance.
    assert packet.stats.budget_used_pct >= 50, packet.stats
    assert packet.stats.digest_calls > 0


def test_preflight_profile_is_emitted_before_digesting(
    tmp_path: Path, mock_model: MinerModel, monkeypatch
) -> None:
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "ops.md").write_text("Team handles 400 claims/day in SAP. " * 600, "utf-8")
    events: list[str] = []
    original_digest = ingest_module.digest_evidence

    def record_digest(*args, **kwargs):
        events.append("digest")
        return original_digest(*args, **kwargs)

    monkeypatch.setattr(ingest_module, "digest_evidence", record_digest)
    ingest_kb(
        kb,
        model=mock_model,
        budget=SMALL,
        preflight_callback=lambda _: events.append("preflight"),
    )

    assert events[:2] == ["preflight", "digest"]


def test_over_budget_without_a_model_trims_whole_chunks(tmp_path: Path) -> None:
    """No model means no digest; evidence is dropped as attributed units."""
    kb = tmp_path / "kb"
    kb.mkdir()
    for i in range(4):
        (kb / f"doc{i}.md").write_text(f"Section {i}. " * 300, encoding="utf-8")
    packet = ingest_kb(kb, budget=SMALL)

    assert packet.stats.truncated
    assert not packet.stats.digested
    assert packet.stats.evidence_tokens <= SMALL.evidence_tokens
    assert [chunk.id for chunk in packet.chunks] == [
        f"S{i}" for i in range(1, len(packet.chunks) + 1)
    ]
    # Chunks are never cut mid-way: each retains its full text.
    for chunk in packet.chunks:
        assert chunk.tokens == estimate_tokens(chunk.text)


def test_oversized_single_file_is_digested_not_hard_cut(
    tmp_path: Path, mock_model: MinerModel
) -> None:
    """A 220k-char brief used to be truncated mid-sentence to 18% of its content."""
    path = tmp_path / "brief.md"
    path.write_text(
        "\n\n".join(f"## Section {i}\n\nProcess {i} detail with volumes." for i in range(400)),
        encoding="utf-8",
    )
    packet = ingest_file(path, model=mock_model, budget=SMALL)
    assert packet.stats.digested
    assert packet.stats.evidence_tokens <= SMALL.evidence_tokens


def test_digest_results_are_cached_across_runs(
    tmp_path: Path, mock_model: MinerModel
) -> None:
    kb = tmp_path / "kb"
    kb.mkdir()
    for i in range(4):
        (kb / f"doc{i}.md").write_text(f"Claims detail {i}. " * 200, encoding="utf-8")
    cache = tmp_path / "cache"

    first = ingest_kb(kb, model=mock_model, budget=SMALL, cache_root=cache)
    second = ingest_kb(kb, model=mock_model, budget=SMALL, cache_root=cache)

    assert first.stats.digest_calls > 0
    assert second.stats.digest_calls == 0
    assert second.stats.digest_cache_hits > 0
    assert first.overview == second.overview


def test_json_is_not_inflated_by_pretty_printing(tmp_path: Path) -> None:
    """indent=2 re-serialization used to nearly double a JSON file's token cost."""
    path = tmp_path / "records.json"
    records = [{"id": i, "system": "SAP", "hours": 3} for i in range(600)]
    path.write_text(json.dumps(records, separators=(",", ":")), encoding="utf-8")

    packet = ingest_file(path)
    assert packet.stats.evidence_chars < path.stat().st_size
    assert "array of 600 records" in packet.overview


def test_chunks_carry_source_and_are_sequentially_numbered(tmp_path: Path) -> None:
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "a.md").write_text("# A\n\nalpha\n\n## A2\n\nsecond\n", encoding="utf-8")
    (kb / "b.md").write_text("# B\n\nbeta\n", encoding="utf-8")
    packet = ingest_kb(kb)

    assert [c.id for c in packet.chunks] == [f"S{i}" for i in range(1, len(packet.chunks) + 1)]
    assert {c.source for c in packet.chunks} == {"a.md", "b.md"}
    assert packet.chunk_ids() == {c.id for c in packet.chunks}
    assert "[S1]" in packet.overview


def test_idea_heading_punctuation_does_not_leak_into_the_domain() -> None:
    packet = ingest_idea("DHL in Germany — operational domain description:\n\nDrivers scan parcels.")
    assert packet.domain == "DHL in Germany — operational domain description"
    assert packet.domain_slug == "dhl-in-germany-operational-domain-description"
