"""Document and spreadsheet readers: PDF, DOCX, PPTX, CSV, XLSX."""

from __future__ import annotations

from pathlib import Path

import pytest

from automation_miner.readers import (
    CsvReader,
    PdfReader,
    ReaderError,
    build_registry,
)
from automation_miner.readers.documents import pdf_extraction_quality

from pdf_fixtures import make_pdf


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


def test_pdf_records_empty_pages_as_failed_telemetry(monkeypatch) -> None:
    pypdf = pytest.importorskip("pypdf")

    class Page:
        def extract_text(self) -> str:
            return ""

    class Document:
        pages = [Page(), Page()]
        is_encrypted = False

    monkeypatch.setattr(pypdf, "PdfReader", lambda _: Document())
    with pytest.raises(ReaderError) as raised:
        PdfReader().parse(Path("scanned.pdf"), b"pdf")

    assert raised.value.meta["pages_failed"] == 2
    assert "p.1: no extractable text" in raised.value.meta["page_errors"]


# ---------------------------------------------------------------------------
# Encoding
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


def test_pdf_page_extraction_errors_are_retained_in_metadata(
    tmp_path: Path, monkeypatch
) -> None:
    pypdf = pytest.importorskip("pypdf")

    class Good:
        def extract_text(self) -> str:
            return "Claims arrive by fax and are keyed into SAP by two clerks."

    class Broken:
        def extract_text(self) -> str:
            raise ValueError("broken character map")

    class Document:
        pages = [Good(), Broken(), Good()]
        is_encrypted = False

    monkeypatch.setattr(pypdf, "PdfReader", lambda _: Document())
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"%PDF")
    meta = PdfReader().read(path).meta

    assert meta["pages"] == 3 and meta["pages_with_text"] == 2
    assert meta["pages_failed"] == 1
    assert "p.2: ValueError" in str(meta["page_errors"])


def test_reader_notes_do_not_leak_between_files(tmp_path: Path) -> None:
    """Per-file facts live for one read, never on the shared reader instance."""
    reader = CsvReader()
    big, small = tmp_path / "big.csv", tmp_path / "small.csv"
    big.write_text("a,b\n" + "1,2\n" * 30, encoding="utf-8")
    small.write_text("a\n1\n", encoding="utf-8")
    assert reader.read(big).meta["rows"] == 30
    assert reader.read(small).meta["rows"] == 1
    assert not [name for name in vars(reader) if name.startswith("_")]


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
