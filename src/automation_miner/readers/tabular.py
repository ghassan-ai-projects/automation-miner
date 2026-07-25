"""CSV/TSV and Excel readers.

Spreadsheets are profiled, not dumped. A 50,000-row claims export tells the
miner nothing extra past its shape — column names, inferred types, value
distributions for low-cardinality fields — plus a sample of real rows. That is
a few hundred characters instead of megabytes, and it is what an automation
analyst actually reasons about ("8 columns, 3 source systems, 50k rows/quarter").

Row counts and column profiles come from a bounded streaming scan, so one huge
file cannot exhaust memory or stall ingestion.
"""

from __future__ import annotations

import csv
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

DEFAULT_SAMPLE_ROWS = 20
DEFAULT_SCAN_ROWS = 20_000
LOW_CARDINALITY = 12
MAX_PROFILE_COLUMNS = 60

_INT_RE = re.compile(r"^[+-]?\d{1,15}$")
_DECIMAL_RE = re.compile(r"^[+-]?(?:\d+[.,]\d+|\d+)$")
_DATE_RE = re.compile(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}([ T]\d{1,2}:\d{2})?")
_MONEY_RE = re.compile(r"^[€$£]\s?[\d.,]+$|^[\d.,]+\s?(?:EUR|USD|GBP)$", re.IGNORECASE)


def _infer_kind(values: list[str]) -> str:
    """Classify a column from its non-empty sample values."""
    sample = [v.strip() for v in values if v and v.strip()][:200]
    if not sample:
        return "empty"
    if all(_INT_RE.match(v) for v in sample):
        return "integer"
    if all(_MONEY_RE.match(v) for v in sample):
        return "money"
    if all(_DECIMAL_RE.match(v) for v in sample):
        return "decimal"
    if all(_DATE_RE.match(v) for v in sample):
        return "date"
    if all(v.lower() in {"true", "false", "yes", "no", "y", "n", "0", "1"} for v in sample):
        return "boolean"
    return "text"


def _profile_columns(headers: list[str], rows: list[list[str]]) -> list[str]:
    """One human-readable profile line per column."""
    lines: list[str] = []
    for index, header in enumerate(headers[:MAX_PROFILE_COLUMNS]):
        column = [row[index] for row in rows if index < len(row)]
        kind = _infer_kind(column)
        distinct = {v.strip() for v in column if v and v.strip()}
        label = header.strip() or f"column {index + 1}"
        if not distinct:
            lines.append(f"  {label} — always empty")
        elif len(distinct) <= LOW_CARDINALITY:
            values = ", ".join(sorted(distinct)[:LOW_CARDINALITY])
            lines.append(f"  {label} — {kind}, {len(distinct)} distinct: {values}")
        else:
            examples = ", ".join(list(dict.fromkeys(v.strip() for v in column if v.strip()))[:3])
            lines.append(f"  {label} — {kind}, {len(distinct)}+ distinct, e.g. {examples}")
    if len(headers) > MAX_PROFILE_COLUMNS:
        lines.append(f"  ... and {len(headers) - MAX_PROFILE_COLUMNS} further columns")
    return lines


def _table_block(headers: list[str], rows: list[list[str]]) -> str:
    """Render sampled rows as a pipe table the model can read directly."""
    width = len(headers)
    out = ["| " + " | ".join(h.strip() or f"c{i+1}" for i, h in enumerate(headers)) + " |"]
    out.append("|" + "|".join(["---"] * width) + "|")
    for row in rows:
        cells = [(row[i] if i < len(row) else "").replace("|", "\\|").strip() for i in range(width)]
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)


def _sample_indices(total: int, budget: int) -> tuple[int, int]:
    """Split a row budget into a head and a tail slice."""
    if total <= budget:
        return total, 0
    tail = min(budget // 4, max(0, total - budget))
    return budget - tail, tail


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
        scan_limit = self.option("scan_rows", DEFAULT_SCAN_ROWS)
        sample_budget = self.option("sample_rows", DEFAULT_SAMPLE_ROWS)

        reader = csv.reader(io.StringIO(text), delimiter=delimiter)
        try:
            headers = next(reader)
        except StopIteration as exc:
            raise ReaderError("file has no header row") from exc
        rows: list[list[str]] = []
        truncated_scan = False
        for row in reader:
            if len(rows) >= scan_limit:
                truncated_scan = True
                break
            if any(cell.strip() for cell in row):
                rows.append(row)

        self._rows, self._cols, self._capped = len(rows), len(headers), truncated_scan
        count = f"{len(rows):,}{'+' if truncated_scan else ''}"
        summary = [
            f"{path.name}: {count} data rows, {len(headers)} columns, delimiter {delimiter!r}.",
            "",
            "Columns:",
            *_profile_columns(headers, rows),
        ]
        if truncated_scan:
            summary += ["", f"(profile scan capped at {scan_limit:,} rows)"]
        segments = [Segment(text="\n".join(summary), locator=f"{path.name} (profile)")]

        head_n, tail_n = _sample_indices(len(rows), sample_budget)
        if head_n:
            segments.append(
                Segment(
                    text=_table_block(headers, rows[:head_n]),
                    locator=f"rows 1-{head_n}",
                )
            )
        if tail_n:
            start = len(rows) - tail_n + 1
            segments.append(
                Segment(
                    text=_table_block(headers, rows[-tail_n:]),
                    locator=f"rows {start}-{len(rows)}",
                )
            )
        return segments

    def _delimiter(self, path: Path, text: str) -> str:
        if path.suffix.lower() == ".tsv":
            return "\t"
        if path.suffix.lower() == ".psv":
            return "|"
        try:
            return csv.Sniffer().sniff(text[:8_192], delimiters=",;\t|").delimiter
        except csv.Error:
            return ","

    def meta(self, path: Path, data: bytes, segments: list[Segment]) -> dict[str, str | int]:
        info = super().meta(path, data, segments)
        info["rows"] = getattr(self, "_rows", 0)
        info["columns"] = getattr(self, "_cols", 0)
        if getattr(self, "_capped", False):
            info["scan_capped"] = "true"
        return info


class XlsxReader(BaseReader):
    """Excel workbooks via openpyxl — one profile + sample per sheet."""

    name = "xlsx"
    suffixes = (".xlsx", ".xlsm")
    media_type = MediaType.TABULAR
    binary = True

    def available(self) -> Availability:
        return missing_dependency("openpyxl", "xlsx")

    def parse(self, path: Path, data: bytes) -> list[Segment]:
        import openpyxl

        scan_limit = self.option("scan_rows", DEFAULT_SCAN_ROWS)
        sample_budget = self.option("sample_rows", DEFAULT_SAMPLE_ROWS)
        try:
            book = openpyxl.load_workbook(
                io.BytesIO(data), read_only=True, data_only=True, keep_links=False
            )
        except Exception as exc:  # openpyxl raises a wide range of parse errors
            raise ReaderError(f"cannot open workbook: {exc}") from exc

        segments: list[Segment] = []
        self._sheets = 0
        try:
            for sheet in book.worksheets:
                rows_iter = sheet.iter_rows(values_only=True)
                headers = [
                    str(c) if c is not None else "" for c in next(rows_iter, ()) or ()
                ]
                if not any(h.strip() for h in headers):
                    continue
                rows: list[list[str]] = []
                capped = False
                for values in rows_iter:
                    if len(rows) >= scan_limit:
                        capped = True
                        break
                    cells = [str(v) if v is not None else "" for v in values]
                    if any(c.strip() for c in cells):
                        rows.append(cells)
                self._sheets += 1
                count = f"{len(rows):,}{'+' if capped else ''}"
                summary = [
                    f"Sheet {sheet.title!r}: {count} data rows, {len(headers)} columns.",
                    "",
                    "Columns:",
                    *_profile_columns(headers, rows),
                ]
                segments.append(
                    Segment(text="\n".join(summary), locator=f"{sheet.title} (profile)")
                )
                head_n, tail_n = _sample_indices(len(rows), sample_budget)
                if head_n:
                    segments.append(
                        Segment(
                            text=_table_block(headers, rows[:head_n]),
                            locator=f"{sheet.title}!rows 2-{head_n + 1}",
                        )
                    )
                if tail_n:
                    segments.append(
                        Segment(
                            text=_table_block(headers, rows[-tail_n:]),
                            locator=f"{sheet.title}!last {tail_n} rows",
                        )
                    )
        finally:
            book.close()

        if not segments:
            raise ReaderError("workbook has no sheet with a usable header row")
        return segments

    def meta(self, path: Path, data: bytes, segments: list[Segment]) -> dict[str, str | int]:
        info = super().meta(path, data, segments)
        info["sheets"] = getattr(self, "_sheets", 0)
        return info
