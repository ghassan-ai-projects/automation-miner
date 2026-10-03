"""CSV/TSV and Excel readers.

Large spreadsheets are profiled, not dumped: column types, numeric statistics,
value distributions for low-cardinality fields, and a sample of real rows that
always includes the unusual ones. Small tables are kept whole. See
``table_profile`` for the rules.

Row counts and column profiles come from a bounded streaming scan, so one huge
file cannot exhaust memory or stall ingestion.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any, Iterable, Sequence

from automation_miner.readers.table_profile import table_segments
from automation_miner.readers.base import (
    Availability,
    BaseReader,
    MediaType,
    ReaderError,
    Segment,
    missing_dependency,
)

DEFAULT_SAMPLE_ROWS = 20
DEFAULT_SCAN_ROWS = 20_000


def _scan(rows: Iterable[Sequence[object]], limit: int) -> tuple[list[list[str]], bool]:
    """Non-empty rows as strings, up to ``limit``; True when the scan was capped."""
    kept: list[list[str]] = []
    for values in rows:
        if len(kept) >= limit:
            return kept, True
        cells = ["" if v is None else str(v) for v in values]
        if any(cell.strip() for cell in cells):
            kept.append(cells)
    return kept, False


class CsvReader(BaseReader):
    """Delimited text: ``.csv``, ``.tsv``, ``.psv``."""

    name = "csv"
    suffixes = (".csv", ".tsv", ".psv")
    media_type = MediaType.TABULAR

    def parse(self, path: Path, data: bytes) -> list[Segment]:
        text = self.decode(data)
        if not text.strip():
            raise ReaderError("file is empty")
        delimiter = self._delimiter(path, text)
        limit = self.option("scan_rows", DEFAULT_SCAN_ROWS)
        reader = csv.reader(io.StringIO(text), delimiter=delimiter)
        try:
            headers = next(reader)
        except StopIteration as exc:
            raise ReaderError("file has no header row") from exc
        rows, capped = _scan(reader, limit)
        self.note("rows", len(rows))
        self.note("columns", len(headers))
        if capped:
            self.note("scan_capped", "true")
        count = f"{len(rows):,}{'+' if capped else ''}"
        summary = [f"{path.name}: {count} data rows, {len(headers)} columns, delimiter {delimiter!r}."]
        if capped:
            summary.append(f"(profile scan capped at {limit:,} rows)")
        sample = self.option("sample_rows", DEFAULT_SAMPLE_ROWS)
        return table_segments(path.name, headers, rows, summary, sample)

    def _delimiter(self, path: Path, text: str) -> str:
        if path.suffix.lower() == ".tsv":
            return "\t"
        if path.suffix.lower() == ".psv":
            return "|"
        try:
            return csv.Sniffer().sniff(text[:8_192], delimiters=",;\t|").delimiter
        except csv.Error:
            return ","


class XlsxReader(BaseReader):
    """Excel workbooks via openpyxl — one profile + sample per sheet."""

    name = "xlsx"
    suffixes = (".xlsx", ".xlsm")
    media_type = MediaType.TABULAR
    binary = True

    def available(self) -> Availability:
        return missing_dependency("openpyxl", "xlsx")

    def _sheet(self, sheet: Any) -> list[Segment]:
        """Profile and sample one sheet; no segments without a usable header."""
        rows_iter = sheet.iter_rows(values_only=True)
        headers = ["" if c is None else str(c) for c in next(rows_iter, ()) or ()]
        if not any(h.strip() for h in headers):
            return []
        rows, capped = _scan(rows_iter, self.option("scan_rows", DEFAULT_SCAN_ROWS))
        count = f"{len(rows):,}{'+' if capped else ''}"
        summary = [f"Sheet {sheet.title!r}: {count} data rows, {len(headers)} columns."]
        sample = self.option("sample_rows", DEFAULT_SAMPLE_ROWS)
        return table_segments(
            sheet.title, headers, rows, summary, sample, locator_prefix=sheet.title
        )

    def parse(self, path: Path, data: bytes) -> list[Segment]:
        import openpyxl

        try:
            book = openpyxl.load_workbook(
                io.BytesIO(data), read_only=True, data_only=True, keep_links=False
            )
        except Exception as exc:  # openpyxl raises a wide range of parse errors
            raise ReaderError(f"cannot open workbook: {exc}") from exc
        try:
            per_sheet = [self._sheet(sheet) for sheet in book.worksheets]
        finally:
            book.close()
        self.note("sheets", sum(1 for segments in per_sheet if segments))
        segments = [segment for sheet in per_sheet for segment in sheet]
        if not segments:
            raise ReaderError("workbook has no sheet with a usable header row")
        return segments
