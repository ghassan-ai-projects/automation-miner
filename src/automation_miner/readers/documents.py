"""PDF, Word, and PowerPoint readers.

Each needs an optional dependency, so each reports its own availability with an
actionable install hint rather than the file being silently skipped. Locators
are the natural address of the format — ``p.4``, a heading path, ``slide 7`` —
so a citation lands somewhere a human can actually look.

A PDF with no extractable text is a scanned image, not an empty document. That
is reported as such (OCR required) instead of contributing zero evidence while
appearing to have been read.
"""

from __future__ import annotations

import io
import re
from pathlib import Path

from automation_miner.readers.base import (
    Availability,
    BaseReader,
    MediaType,
    ReaderError,
    Segment,
    missing_dependency,
)

MAX_TABLE_ROWS = 50
PDF_SUSPICIOUS_TOKEN_MIN = 20
PDF_SUSPICIOUS_TOKEN_RATIO = 0.02


def pdf_extraction_quality(text: str) -> tuple[float, list[str]]:
    """Estimate whether a PDF's character map corrupted otherwise visible prose.

    Broken ToUnicode maps commonly turn words into ``operaDng`` or ``por;olio``.
    This is not mojibake that an encoding retry can repair. A conservative
    threshold avoids flagging a handful of camelCase identifiers in technical
    PDFs while catching document-wide substitution patterns.
    """
    tokens = re.findall(r"\S+", text)
    if not tokens:
        return 0.0, []
    suspicious = [
        token
        for token in tokens
        if re.search(r"[a-z][A-Z]", token)
        or re.search(r"[A-Za-z][;\"|][A-Za-z]", token)
        or "\ufffd" in token
    ]
    ratio = len(suspicious) / len(tokens)
    quality = max(0.0, round(1.0 - ratio, 3))
    return quality, suspicious[:8]


class PdfReader(BaseReader):
    """PDF text extraction via pypdf, one segment per page."""

    name = "pdf"
    suffixes = (".pdf",)
    media_type = MediaType.DOCUMENT
    binary = True

    def available(self) -> Availability:
        return missing_dependency("pypdf", "pdf")

    def parse(self, path: Path, data: bytes) -> list[Segment]:
        import pypdf

        try:
            document = pypdf.PdfReader(io.BytesIO(data))
        except Exception as exc:  # pypdf raises several unrelated error types
            raise ReaderError(f"cannot open PDF: {exc}") from exc

        if document.is_encrypted:
            try:
                opened = document.decrypt("")
            except Exception:
                opened = 0
            if not opened:
                raise ReaderError("PDF is password-protected")

        self._pages = len(document.pages)
        self._page_errors: list[str] = []
        segments: list[Segment] = []
        for number, page in enumerate(document.pages, 1):
            try:
                text = page.extract_text() or ""
            except Exception as exc:
                self._page_errors.append(f"p.{number}: {type(exc).__name__}: {exc}")
                continue
            if text.strip():
                segments.append(Segment(text=text, locator=f"p.{number}"))
            else:
                self._page_errors.append(f"p.{number}: no extractable text")

        if not segments:
            raise ReaderError(
                f"no extractable text in {self._pages} page(s) — likely a scanned "
                "PDF; OCR it before mining",
                meta={
                    "pages": self._pages,
                    "pages_with_text": 0,
                    "pages_failed": len(self._page_errors),
                    "page_errors": "; ".join(self._page_errors[:8]),
                },
            )
        quality, examples = pdf_extraction_quality("\n".join(s.text for s in segments))
        self._extraction_quality = quality
        if (
            examples
            and (1.0 - quality) >= PDF_SUSPICIOUS_TOKEN_RATIO
            and sum(
                1
                for segment in segments
                for token in re.findall(r"\S+", segment.text)
                if re.search(r"[a-z][A-Z]", token)
                or re.search(r"[A-Za-z][;\"|][A-Za-z]", token)
                or "\ufffd" in token
            )
            >= PDF_SUSPICIOUS_TOKEN_MIN
            and not bool(self.options.get("allow_low_quality", False))
        ):
            sample = ", ".join(examples)
            raise ReaderError(
                "low-quality PDF text extraction detected "
                f"(quality {quality:.1%}; examples: {sample}). OCR the PDF or set "
                "[readers.pdf] allow_low_quality = true to override"
            )
        return segments

    def meta(self, path: Path, data: bytes, segments: list[Segment]) -> dict[str, str | int | float | bool]:
        info = super().meta(path, data, segments)
        info["pages"] = getattr(self, "_pages", 0)
        info["pages_with_text"] = len(segments)
        info["pages_failed"] = len(getattr(self, "_page_errors", []))
        if self._page_errors:
            info["page_errors"] = "; ".join(self._page_errors[:8])
        info["extraction_quality"] = getattr(self, "_extraction_quality", 1.0)
        return info


class DocxReader(BaseReader):
    """Word documents via python-docx, segmented on heading styles."""

    name = "docx"
    suffixes = (".docx",)
    media_type = MediaType.DOCUMENT
    binary = True

    def available(self) -> Availability:
        return missing_dependency("docx", "docx")

    def parse(self, path: Path, data: bytes) -> list[Segment]:
        import docx

        try:
            document = docx.Document(io.BytesIO(data))
        except Exception as exc:
            raise ReaderError(f"cannot open document: {exc}") from exc

        segments: list[Segment] = []
        stack: list[tuple[int, str]] = []
        buffer: list[str] = []
        locator = ""

        def flush() -> None:
            body = "\n".join(buffer).strip()
            if body:
                segments.append(Segment(text=body, locator=locator))
            buffer.clear()

        for paragraph in document.paragraphs:
            text = paragraph.text.strip()
            level = self._heading_level(paragraph)
            if level and text:
                flush()
                while stack and stack[-1][0] >= level:
                    stack.pop()
                stack.append((level, text))
                locator = " > ".join(title for _, title in stack)
            if text:
                buffer.append(text)
        flush()

        self._tables = len(document.tables)
        for index, table in enumerate(document.tables, 1):
            rows = [
                " | ".join(cell.text.strip().replace("\n", " ") for cell in row.cells)
                for row in table.rows[:MAX_TABLE_ROWS]
            ]
            rows = [row for row in rows if row.replace("|", "").strip()]
            if rows:
                note = (
                    f"\n(+{len(table.rows) - MAX_TABLE_ROWS} further rows)"
                    if len(table.rows) > MAX_TABLE_ROWS
                    else ""
                )
                segments.append(
                    Segment(text="\n".join(rows) + note, locator=f"table {index}")
                )

        if not segments:
            raise ReaderError("document contains no extractable text")
        return segments

    @staticmethod
    def _heading_level(paragraph: object) -> int:
        name = getattr(getattr(paragraph, "style", None), "name", "") or ""
        if not name.lower().startswith("heading"):
            return 0
        tail = name.split()[-1]
        return int(tail) if tail.isdigit() else 1

    def meta(self, path: Path, data: bytes, segments: list[Segment]) -> dict[str, str | int | float | bool]:
        info = super().meta(path, data, segments)
        info["tables"] = getattr(self, "_tables", 0)
        return info


class PptxReader(BaseReader):
    """PowerPoint decks via python-pptx, one segment per slide plus notes."""

    name = "pptx"
    suffixes = (".pptx",)
    media_type = MediaType.PRESENTATION
    binary = True

    def available(self) -> Availability:
        return missing_dependency("pptx", "pptx")

    def parse(self, path: Path, data: bytes) -> list[Segment]:
        from pptx import Presentation

        try:
            deck = Presentation(io.BytesIO(data))
        except Exception as exc:
            raise ReaderError(f"cannot open presentation: {exc}") from exc

        segments: list[Segment] = []
        self._slides = 0
        for number, slide in enumerate(deck.slides, 1):
            self._slides += 1
            parts: list[str] = []
            for shape in slide.shapes:
                if shape.has_text_frame:
                    text = shape.text_frame.text.strip()
                    if text:
                        parts.append(text)
                if getattr(shape, "has_table", False):
                    for row in shape.table.rows:
                        cells = " | ".join(c.text.strip() for c in row.cells)
                        if cells.replace("|", "").strip():
                            parts.append(cells)
            if slide.has_notes_slide:
                notes = slide.notes_slide.notes_text_frame.text.strip()
                if notes:
                    parts.append(f"Speaker notes: {notes}")
            if parts:
                segments.append(Segment(text="\n".join(parts), locator=f"slide {number}"))

        if not segments:
            raise ReaderError(f"no extractable text in {self._slides} slide(s)")
        return segments

    def meta(self, path: Path, data: bytes, segments: list[Segment]) -> dict[str, str | int | float | bool]:
        info = super().meta(path, data, segments)
        info["slides"] = getattr(self, "_slides", 0)
        return info
