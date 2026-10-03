"""Turn a parsed table into evidence segments a model can reason over.

A real run read a 26-row weekly metrics CSV as "rows 1-15" plus "rows 22-26"
and dropped weeks 16-21 — including a storm spike of 2,980 claims, the one row
that mattered. Its numeric columns were described as "e.g. 1720, 1810, 1795".
Operations data is about magnitude and exceptions, so now:

* small tables are included in full (they cost a few hundred tokens);
* numeric columns get min / median / mean / max / total;
* large tables are sampled as head + tail + the rows with unusual values,
  so peaks and outages survive sampling.
"""

from __future__ import annotations

import re
import statistics

from automation_miner.readers.base import Segment

LOW_CARDINALITY = 12
MAX_PROFILE_COLUMNS = 60
FULL_TABLE_ROWS = 60
FULL_TABLE_CHARS = 8_000
BLOCK_ROWS = 30
OUTLIER_ROWS = 8
OUTLIER_RATIO = 1.5

_INT_RE = re.compile(r"^[+-]?\d{1,15}$")
_DECIMAL_RE = re.compile(r"^[+-]?(?:\d{1,3}(?:[.,]\d{3})+|\d+)(?:[.,]\d+)?$")
_DATE_RE = re.compile(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}([ T]\d{1,2}:\d{2})?")
_MONEY_RE = re.compile(r"^[€$£]\s?[\d.,]+$|^[\d.,]+\s?(?:EUR|USD|GBP)$", re.IGNORECASE)
_NUMERIC_KINDS = {"integer", "decimal", "money"}


def infer_kind(values: list[str]) -> str:
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


def to_number(value: str) -> float | None:
    """Parse 1,234 / 1.234,5 / €12.50 / 12.5 EUR; None when not numeric."""
    text = re.sub(r"[€$£]|EUR|USD|GBP|\s", "", value.strip(), flags=re.IGNORECASE)
    if not text:
        return None
    if "," in text and "." in text:
        text = text.replace(",", "") if text.rfind(".") > text.rfind(",") else (
            text.replace(".", "").replace(",", ".")
        )
    elif "," in text:
        head, _, tail = text.rpartition(",")
        text = f"{head.replace(',', '')}.{tail}" if len(tail) <= 2 else text.replace(",", "")
    try:
        return float(text)
    except ValueError:
        return None


def _fmt(value: float) -> str:
    return f"{value:,.0f}" if abs(value) >= 100 or value == int(value) else f"{value:,.2f}"


def _numbers(rows: list[list[str]], index: int) -> list[float]:
    found = (to_number(row[index]) for row in rows if index < len(row))
    return [value for value in found if value is not None]


def _column_line(label: str, kind: str, column: list[str], numbers: list[float]) -> str:
    distinct = {v.strip() for v in column if v and v.strip()}
    if not distinct:
        return f"  {label} — always empty"
    if numbers:
        return (
            f"  {label} — {kind}: min {_fmt(min(numbers))}, "
            f"median {_fmt(statistics.median(numbers))}, "
            f"mean {_fmt(statistics.fmean(numbers))}, max {_fmt(max(numbers))}, "
            f"total {_fmt(sum(numbers))}"
        )
    if len(distinct) <= LOW_CARDINALITY:
        values = ", ".join(sorted(distinct)[:LOW_CARDINALITY])
        return f"  {label} — {kind}, {len(distinct)} distinct: {values}"
    examples = ", ".join(list(dict.fromkeys(v.strip() for v in column if v.strip()))[:3])
    return f"  {label} — {kind}, {len(distinct)}+ distinct, e.g. {examples}"


def profile_columns(headers: list[str], rows: list[list[str]]) -> list[str]:
    """One human-readable profile line per column, with statistics for numbers."""
    lines: list[str] = []
    for index, header in enumerate(headers[:MAX_PROFILE_COLUMNS]):
        column = [row[index] for row in rows if index < len(row)]
        kind = infer_kind(column)
        numbers = _numbers(rows, index) if kind in _NUMERIC_KINDS else []
        lines.append(_column_line(header.strip() or f"column {index + 1}", kind, column, numbers))
    if len(headers) > MAX_PROFILE_COLUMNS:
        lines.append(f"  ... and {len(headers) - MAX_PROFILE_COLUMNS} further columns")
    return lines


def table_block(headers: list[str], rows: list[list[str]]) -> str:
    """Render rows as a pipe table the model can read directly."""
    width = len(headers)
    out = ["| " + " | ".join(h.strip() or f"c{i+1}" for i, h in enumerate(headers)) + " |"]
    out.append("|" + "|".join(["---"] * width) + "|")
    for row in rows:
        cells = [(row[i] if i < len(row) else "").replace("|", "\\|").strip() for i in range(width)]
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)


def outlier_rows(headers: list[str], rows: list[list[str]], limit: int = OUTLIER_ROWS) -> list[int]:
    """Indices of rows whose numeric values sit far from their column median."""
    scores = [0.0] * len(rows)
    for index in range(min(len(headers), MAX_PROFILE_COLUMNS)):
        column = [row[index] if index < len(row) else "" for row in rows]
        if infer_kind(column) not in _NUMERIC_KINDS:
            continue
        values = [to_number(value) for value in column]
        present = [value for value in values if value is not None]
        if len(present) < 4:
            continue
        median = statistics.median(present)
        if median <= 0:
            continue
        for row_index, value in enumerate(values):
            if value is None:
                continue
            ratio = max(value / median, median / value if value > 0 else OUTLIER_RATIO)
            if ratio >= OUTLIER_RATIO:
                scores[row_index] = max(scores[row_index], ratio)
    ranked = sorted((i for i, s in enumerate(scores) if s > 0), key=lambda i: (-scores[i], i))
    return sorted(ranked[:limit])


def _rows_segment(headers: list[str], rows: list[list[str]], start: int, prefix: str) -> Segment:
    """Rows ``start`` onward (0-based) as one segment addressed by 1-based row numbers."""
    return Segment(
        text=table_block(headers, rows), locator=f"{prefix}rows {start + 1}-{start + len(rows)}"
    )


def _sampled_segments(
    headers: list[str], rows: list[list[str]], sample_rows: int, prefix: str
) -> list[Segment]:
    """Head, tail, and the unusual rows between them, for a table too big to include."""
    head_n = max(1, sample_rows - sample_rows // 4)
    tail_n = min(sample_rows // 4, max(0, len(rows) - head_n))
    segments = [_rows_segment(headers, rows[:head_n], 0, prefix)]
    if tail_n:
        segments.append(_rows_segment(headers, rows[-tail_n:], len(rows) - tail_n, prefix))
    middle = [i for i in outlier_rows(headers, rows) if head_n <= i < len(rows) - tail_n]
    if middle:
        numbers = ", ".join(str(i + 1) for i in middle)
        segments.append(
            Segment(
                text=f"Rows with unusual values (row numbers {numbers}):\n"
                + table_block(headers, [rows[i] for i in middle]),
                locator=f"{prefix}unusual rows",
            )
        )
    return segments


def table_segments(
    label: str,
    headers: list[str],
    rows: list[list[str]],
    summary_head: list[str],
    sample_rows: int,
    locator_prefix: str = "",
) -> list[Segment]:
    """Profile segment plus either the whole table or head, tail, and outliers."""
    prefix = f"{locator_prefix}!" if locator_prefix else ""
    summary = [*summary_head, "", "Columns:", *profile_columns(headers, rows)]
    segments = [Segment(text="\n".join(summary), locator=f"{label} (profile)")]
    if len(rows) > FULL_TABLE_ROWS or len(table_block(headers, rows)) > FULL_TABLE_CHARS:
        return segments + _sampled_segments(headers, rows, sample_rows, prefix)
    for start in range(0, len(rows), BLOCK_ROWS):
        segments.append(_rows_segment(headers, rows[start : start + BLOCK_ROWS], start, prefix))
    return segments
