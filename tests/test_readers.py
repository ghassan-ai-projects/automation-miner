"""Reader subsystem: extraction per format, encoding recovery, plugin discovery.

Document fixtures are built with the real libraries so these exercise actual
parsing rather than a stub. The PDF is hand-assembled to keep the test suite
free of a PDF *writer* dependency.
"""

from __future__ import annotations

import json
from pathlib import Path


from automation_miner.readers import (
    JsonReader,
    MediaType,
    TextReader,
    YamlReader,
    build_registry,
    decode_bytes,
    looks_binary,
    split_markdown,
)



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
