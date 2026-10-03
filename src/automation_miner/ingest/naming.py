"""Readable report titles for file and knowledge-base input.

A run used to be titled after the raw path: a ``claims-intake/`` folder
produced "Automation Mining Report — claims-intake", and the same string
reached every prompt as the domain name. A document that names itself in
its top heading ("Board memo — Digital & Automation Strategy 2027–2029")
says far more than its filename. The slug stays derived from the path, so
run directories, the opportunity registry, and prior-idea memory keep
matching earlier runs of the same input.
"""

from __future__ import annotations

import re

from automation_miner.readers.base import SourceDocument

MAX_TITLE_CHARS = 90

_ORDER_PREFIX = re.compile(r"^\d{1,3}[-_. ]+")
_SEPARATORS = re.compile(r"[-_.]+")
_TOP_HEADING = re.compile(r"^#\s+(?P<title>[^>]+?)\s*(?:>|$)")


def readable_name(stem: str) -> str:
    """``01-claims_intake`` → ``Claims intake``; mixed-case names keep their casing."""
    text = _SEPARATORS.sub(" ", _ORDER_PREFIX.sub("", stem.strip()))
    text = " ".join(text.split())
    if not text:
        return stem
    return text[0].upper() + text[1:] if text.islower() else text


def document_title(document: SourceDocument) -> str:
    """The document's top-level markdown heading, or an empty string."""
    for segment in document.segments:
        match = _TOP_HEADING.match(segment.locator)
        if match:
            title = " ".join(match.group("title").split())
            return title if len(title) <= MAX_TITLE_CHARS else ""
    return ""


def file_title(document: SourceDocument, stem: str) -> str:
    return document_title(document) or readable_name(stem)


__all__ = ["MAX_TITLE_CHARS", "document_title", "file_title", "readable_name"]
