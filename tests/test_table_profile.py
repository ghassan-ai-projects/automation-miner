"""Tabular evidence keeps magnitudes and exceptions, not just the first rows."""

from __future__ import annotations

from automation_miner.readers.table_profile import (
    outlier_rows,
    profile_columns,
    table_segments,
    to_number,
)

HEADERS = ["week", "claims"]


def _rows(count: int, spike_at: int | None = None) -> list[list[str]]:
    rows = [[f"W{i + 1:02d}", "1800"] for i in range(count)]
    if spike_at is not None:
        rows[spike_at][1] = "3400"
    return rows


def test_small_tables_are_kept_whole() -> None:
    """Regression: a 26-row CSV lost rows 16-21, including a storm spike."""
    segments = table_segments("m.csv", HEADERS, _rows(26, spike_at=18), ["m.csv"], 20)
    assert [s.locator for s in segments] == ["m.csv (profile)", "rows 1-26"]
    assert "3400" in segments[1].text


def test_large_tables_keep_head_tail_and_unusual_rows() -> None:
    rows = _rows(500, spike_at=250)
    segments = table_segments("big.csv", HEADERS, rows, ["big.csv"], 20)
    locators = [s.locator for s in segments]
    assert locators == ["big.csv (profile)", "rows 1-15", "rows 496-500", "unusual rows"]
    assert "row numbers 251" in segments[-1].text and "3400" in segments[-1].text


def test_numeric_columns_report_magnitude() -> None:
    line = profile_columns(HEADERS, _rows(4, spike_at=0))[1]
    assert line == "  claims — integer: min 1,800, median 1,800, mean 2,200, max 3,400, total 8,800"


def test_number_parsing_handles_locale_and_currency() -> None:
    assert to_number("1,234") == 1234
    assert to_number("1.234,50") == 1234.5
    assert to_number("€12.50") == 12.5
    assert to_number("12,5") == 12.5
    assert to_number("n/a") is None


def test_outliers_rank_far_values_and_ignore_text() -> None:
    rows = [["a", "10"], ["b", "11"], ["c", "10"], ["d", "40"], ["e", "9"]]
    assert outlier_rows(["name", "value"], rows) == [3]
