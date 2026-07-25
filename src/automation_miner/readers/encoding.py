"""Text decoding that never kills a run, and rarely guesses wrong.

Real knowledge bases are not uniformly UTF-8 — exports from German back-office
systems (this project's own worked example) routinely land as cp1252. A bare
``read_text(encoding="utf-8")`` raises on those, so a single legacy file used to
abort ingestion of an entire folder.

Detection order matters more than it looks. Charset detectors judge coherence
statistically, which is unreliable on short samples: given 77 bytes of latin-1
German, ``charset_normalizer`` picks ``mac_iceland`` and turns *Rückstände* into
*R¸ckst‰nde*. So the order here is

1. byte-order mark — unambiguous when present,
2. an explicit ``[readers] encoding`` override,
3. **UTF-8 strict** — self-validating, and the overwhelmingly common case,
4. a detector, but only with enough bytes to be worth trusting,
5. ``cp1252``, the usual Western business-export encoding,
6. ``latin-1``, which maps every byte and therefore cannot fail.

The winning encoding is recorded on the document so a wrong guess is visible
rather than silent, and can be overridden per workspace.
"""

from __future__ import annotations

# Below this many bytes, statistical detection does more harm than good.
MIN_DETECT_BYTES = 1024

# Byte-order marks, longest first so utf-32 wins over the utf-16 prefix.
_BOMS: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xfe\x00\x00", "utf-32-le"),
    (b"\x00\x00\xfe\xff", "utf-32-be"),
    (b"\xef\xbb\xbf", "utf-8-sig"),
    (b"\xff\xfe", "utf-16-le"),
    (b"\xfe\xff", "utf-16-be"),
)

_FALLBACKS: tuple[str, ...] = ("cp1252", "latin-1")


def _detect(data: bytes) -> str | None:
    """Ask charset-normalizer or chardet, if either is installed."""
    try:
        from charset_normalizer import from_bytes
    except ImportError:
        pass
    else:
        best = from_bytes(data).best()
        if best is not None and best.encoding:
            return str(best.encoding)
    try:
        import chardet
    except ImportError:
        return None
    guess = chardet.detect(data)
    encoding = guess.get("encoding")
    confidence = guess.get("confidence") or 0.0
    return str(encoding) if encoding and confidence >= 0.8 else None


def decode_bytes(data: bytes, preferred: str = "") -> tuple[str, str]:
    """Decode to text, returning ``(text, encoding_used)``.

    Never raises. Normalizes line endings so character budgets and chunk offsets
    are platform-independent.
    """
    if not data:
        return "", "utf-8"

    for bom, encoding in _BOMS:
        if data.startswith(bom):
            return _normalize(data.decode(encoding, errors="replace")), encoding

    candidates: list[str] = []
    if preferred:
        candidates.append(preferred)
    candidates.append("utf-8")
    if len(data) >= MIN_DETECT_BYTES and (detected := _detect(data)):
        candidates.append(detected)
    candidates += _FALLBACKS

    seen: set[str] = set()
    for encoding in candidates:
        key = encoding.lower().replace("_", "-")
        if key in seen:
            continue
        seen.add(key)
        try:
            return _normalize(data.decode(encoding)), encoding
        except (UnicodeDecodeError, LookupError):
            continue
    return _normalize(data.decode("utf-8", errors="replace")), "utf-8/replace"


def _normalize(text: str) -> str:
    """Normalize newlines and strip NULs that some exporters emit."""
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")


def looks_binary(data: bytes, sample: int = 4096) -> bool:
    """Heuristic binary sniff, so an unknown suffix is skipped with a real reason."""
    head = data[:sample]
    if not head:
        return False
    if b"\x00" in head:
        return True
    # Control characters outside tab/newline/form-feed indicate a non-text payload.
    control = sum(1 for byte in head if byte < 9 or 13 < byte < 32)
    return control / len(head) > 0.06
