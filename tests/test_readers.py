"""Reader subsystem: extraction per format, encoding recovery, plugin discovery.

Document fixtures are built with the real libraries so these exercise actual
parsing rather than a stub. The PDF is hand-assembled to keep the test suite
free of a PDF *writer* dependency.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from automation_miner.readers import (
    BaseReader,
    CsvReader,
    JsonReader,
    MediaType,
    PdfReader,
    ReaderError,
    Segment,
    TextReader,
    YamlReader,
    build_registry,
    decode_bytes,
    looks_binary,
    split_markdown,
)
from automation_miner.readers.documents import pdf_extraction_quality
from automation_miner.readers.registry import NEVER_TEXT, ReaderRegistry, _validate


def make_pdf(pages: list[str]) -> bytes:
    """Minimal valid PDF with extractable text, one page per entry."""
    font = 3 + 2 * len(pages)
    objs: dict[int, bytes] = {
        1: b"<</Type/Catalog/Pages 2 0 R>>",
        font: b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    }
    kids = []
    for i, text in enumerate(pages):
        page, content = 3 + 2 * i, 4 + 2 * i
        kids.append(f"{page} 0 R")
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
        objs[page] = (
            f"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents {content} 0 R"
            f"/Resources<</Font<</F1 {font} 0 R>>>>>>"
        ).encode()
        objs[content] = b"<</Length %d>>\nstream\n%s\nendstream" % (len(stream), stream)
    objs[2] = ("<</Type/Pages/Kids[" + " ".join(kids) + f"]/Count {len(pages)}>>").encode()

    out = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for num in sorted(objs):
        offsets[num] = len(out)
        out += f"{num} 0 obj\n".encode() + objs[num] + b"\nendobj\n"
    xref, top = len(out), max(objs)
    out += f"xref\n0 {top + 1}\n".encode() + b"0000000000 65535 f \n"
    for num in range(1, top + 1):
        out += (
            f"{offsets[num]:010d} 00000 n \n".encode()
            if num in offsets
            else b"0000000000 65535 f \n"
        )
    out += f"trailer\n<</Size {top + 1}/Root 1 0 R>>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def test_pdf_character_map_corruption_fails_before_mining(tmp_path: Path) -> None:
    pytest.importorskip("pypdf")
    corrupt = " ".join(["operaDng por;olio transformaDon"] * 30)
    quality, examples = pdf_extraction_quality(corrupt)
    assert quality < 0.9
    assert "operaDng" in examples

    path = tmp_path / "corrupt-map.pdf"
    path.write_bytes(make_pdf([corrupt]))
    with pytest.raises(ReaderError, match="low-quality PDF text extraction"):
        PdfReader().read(path)


def test_pdf_quality_override_is_explicit(tmp_path: Path) -> None:
    pytest.importorskip("pypdf")
    corrupt = " ".join(["operaDng por;olio transformaDon"] * 30)
    path = tmp_path / "corrupt-map.pdf"
    path.write_bytes(make_pdf([corrupt]))
    document = PdfReader(allow_low_quality=True).read(path)
    assert document.meta["extraction_quality"] < 0.9


# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------


def test_utf8_wins_over_statistical_detection() -> None:
    text = "Rückstände: 1.240 Fälle offen. Prüfung erfolgt manuell."
    decoded, encoding = decode_bytes(text.encode("utf-8"))
    assert decoded == text
    assert encoding == "utf-8"


def test_cp1252_german_is_not_mojibake() -> None:
    """A short latin-1 sample must not be handed to the charset detector.

    charset-normalizer picks ``mac_iceland`` for this byte sequence, which turns
    'Rückstände' into 'R¸ckst‰nde'.
    """
    text = "Rückstände: 1.240 Fälle offen. Prüfung erfolgt manuell."
    decoded, encoding = decode_bytes(text.encode("latin-1"))
    assert decoded == text
    assert encoding in {"cp1252", "latin-1"}


def test_explicit_encoding_preference_is_honoured() -> None:
    decoded, encoding = decode_bytes("Fälle".encode("latin-1"), preferred="latin-1")
    assert (decoded, encoding) == ("Fälle", "latin-1")


def test_bom_and_newline_normalization() -> None:
    decoded, encoding = decode_bytes("﻿line\r\ntwo\rthree".encode("utf-8"))
    assert encoding == "utf-8-sig"
    assert decoded == "line\ntwo\nthree"


def test_undecodable_bytes_never_raise() -> None:
    decoded, _ = decode_bytes(bytes([0x81, 0x8D, 0x90, 0xFF, 0xFE, 0x41]))
    assert isinstance(decoded, str)


def test_looks_binary() -> None:
    assert looks_binary(b"PK\x03\x04\x00\x00text")
    assert not looks_binary(b"# heading\n\nplain prose with numbers 42\n")
    assert not looks_binary(b"")


# ---------------------------------------------------------------------------
# Text / markdown / HTML
# ---------------------------------------------------------------------------


def test_markdown_heading_path_locators() -> None:
    segments = split_markdown(
        "# Claims\n\nintro\n\n## Intake\n\nbody\n\n### Validation\n\ndeep\n\n## Escalation\n\nend\n"
    )
    locators = [s.locator for s in segments]
    assert locators == [
        "# Claims",
        "# Claims > ## Intake",
        "# Claims > ## Intake > ### Validation",
        "# Claims > ## Escalation",
    ]


def test_markdown_ignores_hashes_inside_code_fences() -> None:
    segments = split_markdown("# Real\n\n```bash\n# not a heading\n```\n\ntail\n")
    assert [s.locator for s in segments] == ["# Real"]
    assert "not a heading" in segments[0].text


def test_text_reader_plain_file(tmp_path: Path) -> None:
    path = tmp_path / "notes.txt"
    path.write_text("Weekly ops meeting, 90 minutes.\n", encoding="utf-8")
    document = TextReader().read(path)
    assert document.media_type is MediaType.TEXT
    assert len(document.segments) == 1
    assert "Weekly ops" in document.text()


def test_html_strips_scripts_and_tracks_headings(tmp_path: Path) -> None:
    path = tmp_path / "page.html"
    path.write_text(
        "<html><head><style>p{color:red}</style><script>var x=1;</script></head><body>"
        "<h1>Billing</h1><p>Nightly export.</p><h2>Issues</h2><p>Duplicates.</p></body></html>",
        encoding="utf-8",
    )
    document = build_registry().read(path)
    body = document.text()
    assert "var x" not in body and "color:red" not in body
    assert "Nightly export." in body
    assert [s.locator for s in document.segments] == ["Billing", "Billing > Issues"]


# ---------------------------------------------------------------------------
# Structured
# ---------------------------------------------------------------------------


def test_unparseable_json_falls_back_to_text_instead_of_aborting(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text('{"systems": ["SAP",  // truncated export\n', encoding="utf-8")
    document = JsonReader().read(path)
    assert "SAP" in document.text()
    assert "invalid JSON" in str(document.meta["parse_error"])


def test_large_json_array_is_summarized_not_dumped(tmp_path: Path) -> None:
    path = tmp_path / "records.json"
    records = [{"id": i, "system": "SAP", "hours": 3} for i in range(2_000)]
    path.write_text(json.dumps(records), encoding="utf-8")
    document = JsonReader().read(path)
    assert document.chars < 2_000
    assert "array of 2000 records" in document.text()
    assert "id, system, hours" in document.text()


def test_small_jsonl_is_rendered_in_full(tmp_path: Path) -> None:
    """Under the readable limit, fidelity beats compression."""
    path = tmp_path / "events.jsonl"
    path.write_text("\n".join(json.dumps({"id": i}) for i in range(30)), encoding="utf-8")
    text = JsonReader().read(path).text()
    assert '"id": 29' in text


def test_large_jsonl_is_summarized(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text(
        "\n".join(json.dumps({"id": i, "event": "escalated", "system": "SAP"}) for i in range(900)),
        encoding="utf-8",
    )
    document = JsonReader().read(path)
    assert "array of 900 records" in document.text()
    assert document.chars < 1_500


def test_jsonl_skips_unparseable_lines(tmp_path: Path) -> None:
    path = tmp_path / "mixed.jsonl"
    path.write_text('{"id": 1}\nnot json\n{"id": 2}\n', encoding="utf-8")
    document = JsonReader().read(path)
    assert '"id": 2' in document.text()
    assert "1 unparseable line" in str(document.meta["parse_error"])


def test_yaml_multi_document_and_broken_fallback(tmp_path: Path) -> None:
    good = tmp_path / "team.yaml"
    good.write_text("team:\n  size: 3\n---\ncompliance: heavy\n", encoding="utf-8")
    document = YamlReader().read(good)
    assert len(document.segments) == 2
    assert "compliance" in document.text()

    bad = tmp_path / "bad.yaml"
    bad.write_text("key: [unclosed\n  nested: : :\n", encoding="utf-8")
    assert "unclosed" in YamlReader().read(bad).text()


# ---------------------------------------------------------------------------
# Tabular
# ---------------------------------------------------------------------------


def test_csv_is_profiled_with_bounded_sample(tmp_path: Path) -> None:
    path = tmp_path / "claims.csv"
    rows = ["claim_id,system,hours"]
    rows += [f"{i},{['SAP', 'Navision'][i % 2]},{1.5 + i % 3}" for i in range(5_000)]
    path.write_text("\n".join(rows), encoding="utf-8")

    document = CsvReader(sample_rows=8).read(path)
    text = document.text()
    assert document.meta["rows"] == 5_000
    assert document.meta["columns"] == 3
    # The profile replaces the bulk dump: 173 KB of rows must not reach the model.
    assert document.chars < 1_500
    assert "5,000 data rows" in text
    assert "system — text, 2 distinct: Navision, SAP" in text
    assert "claim_id — integer" in text
    assert any(s.locator.startswith("rows 1-") for s in document.segments)


def test_csv_detects_tab_delimiter(tmp_path: Path) -> None:
    path = tmp_path / "systems.tsv"
    path.write_text("system\towner\nSAP\tIT\nNavision\tFinance\n", encoding="utf-8")
    document = CsvReader().read(path)
    assert document.meta["columns"] == 2
    assert "Navision" in document.text()


def test_csv_empty_file_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "blank.csv"
    path.write_text("   \n", encoding="utf-8")
    with pytest.raises(ReaderError, match="empty"):
        CsvReader().read(path)


def test_xlsx_profiles_every_sheet(tmp_path: Path) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    path = tmp_path / "volumes.xlsx"
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Volumes"
    sheet.append(["month", "claims"])
    for i in range(1, 13):
        sheet.append([f"2026-{i:02d}", 8_000 + i])
    owners = book.create_sheet("Owners")
    owners.append(["process", "owner"])
    owners.append(["Intake", "Leistungsabteilung"])
    book.save(path)

    document = build_registry().read(path)
    assert document.meta["sheets"] == 2
    assert "Sheet 'Volumes'" in document.text()
    assert "Leistungsabteilung" in document.text()
    assert any("Volumes!rows" in s.locator for s in document.segments)


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


def test_pdf_pages_become_locators(tmp_path: Path) -> None:
    pytest.importorskip("pypdf")
    path = tmp_path / "regulation.pdf"
    path.write_bytes(make_pdf(["Audit trail retained 10 years.", "Sampling of 5 percent."]))
    document = build_registry().read(path)
    assert document.meta["pages"] == 2
    assert [s.locator for s in document.segments] == ["p.1", "p.2"]
    assert "Audit trail" in document.text()


def test_scanned_pdf_reports_ocr_requirement(tmp_path: Path) -> None:
    pytest.importorskip("pypdf")
    path = tmp_path / "scanned.pdf"
    path.write_bytes(make_pdf([""]))
    with pytest.raises(ReaderError, match="scanned"):
        build_registry().read(path)


def test_docx_heading_path_and_tables(tmp_path: Path) -> None:
    docx = pytest.importorskip("docx")
    path = tmp_path / "onboarding.docx"
    document = docx.Document()
    document.add_heading("Onboarding", level=1)
    document.add_paragraph("Six weeks to productivity.")
    document.add_heading("Week 1", level=2)
    document.add_paragraph("Shadowing only.")
    table = document.add_table(rows=2, cols=2)
    table.rows[0].cells[0].text = "Task"
    table.rows[0].cells[1].text = "Owner"
    table.rows[1].cells[0].text = "Grant SAP access"
    table.rows[1].cells[1].text = "IT"
    document.save(path)

    result = build_registry().read(path)
    assert result.meta["tables"] == 1
    assert "Onboarding > Week 1" in [s.locator for s in result.segments]
    assert "Grant SAP access" in result.text()


def test_pptx_slides(tmp_path: Path) -> None:
    pptx = pytest.importorskip("pptx")
    path = tmp_path / "roadmap.pptx"
    deck = pptx.Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[1])
    slide.shapes.title.text = "Automation Roadmap"
    slide.placeholders[1].text = "Q1: claims intake"
    deck.save(path)

    document = build_registry().read(path)
    assert document.meta["slides"] == 1
    assert document.segments[0].locator == "slide 1"
    assert "claims intake" in document.text()


# ---------------------------------------------------------------------------
# Registry and plugin discovery
# ---------------------------------------------------------------------------


def test_builtin_registry_claims_expected_suffixes() -> None:
    registry = build_registry()
    for suffix in (".md", ".txt", ".json", ".yaml", ".csv", ".html", ".pdf", ".docx", ".xlsx"):
        assert suffix in registry.suffixes, suffix
    assert not registry.errors


def test_unknown_text_suffix_falls_back_to_text(tmp_path: Path) -> None:
    path = tmp_path / "report.sql"
    path.write_text("SELECT count(*) FROM claims; -- run by hand weekly\n", encoding="utf-8")
    document = build_registry().read(path)
    assert document.reader == "text"
    assert "read as text" in str(document.meta["fallback"])


def test_binary_suffix_never_falls_back_to_text(tmp_path: Path) -> None:
    """An uncompressed PDF looks textual in its header — the suffix guard must win."""
    path = tmp_path / "regulation.pdf"
    path.write_bytes(make_pdf(["text"]))
    registry = build_registry({"disabled": ["pdf"]})
    with pytest.raises(ReaderError, match="uv sync --extra pdf"):
        registry.read(path)
    assert ".pdf" in NEVER_TEXT


def test_unregistered_binary_is_skipped_with_reason(tmp_path: Path) -> None:
    path = tmp_path / "logo.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(range(256)))
    with pytest.raises(ReaderError, match="binary"):
        build_registry().read(path)


def test_size_cap_and_empty_file(tmp_path: Path) -> None:
    big = tmp_path / "huge.txt"
    big.write_text("x" * 5_000, encoding="utf-8")
    with pytest.raises(ReaderError, match="max_file_bytes"):
        build_registry({"max_file_bytes": 1_000}).read(big)

    empty = tmp_path / "empty.md"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(ReaderError, match="empty"):
        build_registry().read(empty)


def test_per_reader_options_from_config(tmp_path: Path) -> None:
    path = tmp_path / "rows.csv"
    path.write_text("\n".join(["a,b"] + [f"{i},{i}" for i in range(100)]), encoding="utf-8")
    small = build_registry({"csv": {"sample_rows": 4}}).read(path)
    large = build_registry({"csv": {"sample_rows": 40}}).read(path)
    assert large.chars > small.chars


def test_disabled_reader_is_not_registered() -> None:
    registry = build_registry({"disabled": ["pptx", "xlsx"]})
    assert "pptx" not in registry.registrations
    assert ".xlsx" not in registry.suffixes


def test_enabled_allowlist_restricts_registry() -> None:
    registry = build_registry({"enabled": ["text", "json"]})
    assert set(registry.registrations) == {"text", "json"}
    assert ".pdf" not in registry.suffixes


def test_custom_reader_from_config_needs_no_package_change(tmp_path: Path) -> None:
    registry = build_registry(
        {"custom": [{"suffixes": [".vtt"], "name": "vtt", "factory": f"{__name__}:_VttReader"}]}
    )
    path = tmp_path / "standup.vtt"
    path.write_text("WEBVTT\n\n00:00:01.000 --> 00:00:04.000\nManual reconciliation.\n", "utf-8")
    document = registry.read(path)
    assert document.reader == "vtt"
    assert "Manual reconciliation." in document.text()
    assert [r.source for r in registry.describe() if r.name == "vtt"] == ["miner.toml"]


def test_custom_reader_outranks_builtin_for_same_suffix() -> None:
    registry = build_registry(
        {"custom": [{"suffixes": [".md"], "name": "vtt", "factory": f"{__name__}:_VttReader"}]}
    )
    assert registry.reader_for(Path("x.md")).name == "vtt"


def test_broken_plugin_is_reported_not_fatal(tmp_path: Path) -> None:
    registry = build_registry({"custom": [{"suffixes": [".zzz"], "factory": "nope.absent:Thing"}]})
    assert any("failed to load" in error for error in registry.errors)
    path = tmp_path / "still.md"
    path.write_text("# works\n", encoding="utf-8")
    assert registry.read(path).reader == "text"


def test_registry_rejects_malformed_readers() -> None:
    class NoSuffixes(BaseReader):
        name = "broken"
        suffixes = ()

    registry = ReaderRegistry()
    registry.register(NoSuffixes(), source="test")
    assert registry.registrations == {}
    assert "declares no suffixes" in registry.errors[0]
    assert "no usable 'name'" in _validate(object())


def test_describe_reports_availability() -> None:
    rows = {row.name: row for row in build_registry().describe()}
    assert rows["text"].available
    assert rows["csv"].media_type == "tabular"
    assert all(row.source == "builtin" for row in rows.values())


class _VttReader(BaseReader):
    """Stand-in for a third-party reader, referenced by config in the tests above."""

    name = "vtt"
    suffixes = (".vtt",)
    media_type = MediaType.TEXT

    def parse(self, path: Path, data: bytes) -> list[Segment]:
        lines = [
            line.strip()
            for line in self.decode(data).split("\n")
            if line.strip() and line.strip() != "WEBVTT" and "-->" not in line
        ]
        return [Segment(text=" ".join(lines), locator="transcript")]
