"""Plain-text, markdown, and HTML readers.

Markdown is segmented on ATX headings so every segment carries its heading path
as a locator (``"# Claims > ## Rework"``). That path is what makes a later
citation legible to a human reviewing the source document.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

from automation_miner.readers.base import BaseReader, MediaType, Segment

_ATX = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")

_MARKDOWN_SUFFIXES = {".md", ".markdown", ".mdx"}


def split_markdown(text: str) -> list[Segment]:
    """Segment markdown by heading, tracking the full heading path per section.

    Fenced code blocks are respected so a ``#`` comment inside a shell snippet
    is not mistaken for a heading.
    """
    segments: list[Segment] = []
    stack: list[tuple[int, str]] = []
    buffer: list[str] = []
    locator = ""
    fence: str | None = None

    def flush() -> None:
        body = "\n".join(buffer).strip()
        if body:
            segments.append(Segment(text=body, locator=locator))
        buffer.clear()

    for line in text.split("\n"):
        opener = _FENCE.match(line)
        if opener:
            marker = opener.group(1)
            if fence is None:
                fence = marker
            elif marker == fence:
                fence = None
        if fence is None:
            heading = _ATX.match(line)
            if heading:
                flush()
                level = len(heading.group(1))
                while stack and stack[-1][0] >= level:
                    stack.pop()
                stack.append((level, heading.group(2).strip()))
                locator = " > ".join(f"{'#' * lv} {title}" for lv, title in stack)
        buffer.append(line)
    flush()
    return segments


class TextReader(BaseReader):
    """Markdown, plain text, and other line-oriented prose formats."""

    name = "text"
    suffixes = (
        ".md",
        ".markdown",
        ".mdx",
        ".txt",
        ".text",
        ".rst",
        ".adoc",
        ".asciidoc",
        ".org",
        ".log",
        ".tex",
    )
    media_type = MediaType.TEXT

    def parse(self, path: Path, data: bytes) -> list[Segment]:
        text = self.decode(data)
        if path.suffix.lower() in _MARKDOWN_SUFFIXES:
            segments = split_markdown(text)
            if segments:
                return segments
        return [Segment(text=text)]


class _HtmlExtractor(HTMLParser):
    """Collect visible text, opening a new segment at each h1-h3."""

    _SKIP = {"script", "style", "noscript", "template", "svg"}
    _BLOCK = {
        "p", "div", "br", "li", "tr", "section", "article", "header", "footer",
        "h1", "h2", "h3", "h4", "h5", "h6", "td", "th", "blockquote", "pre",
    }
    _HEADINGS = {"h1": 1, "h2": 2, "h3": 3}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.segments: list[Segment] = []
        self._buffer: list[str] = []
        self._skip_depth = 0
        self._stack: list[tuple[int, str]] = []
        self._locator = ""
        self._heading_level: int | None = None
        self._heading_text: list[str] = []

    def _flush(self) -> None:
        body = " ".join(" ".join(self._buffer).split()).strip()
        if body:
            self.segments.append(Segment(text=body, locator=self._locator))
        self._buffer = []

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag in self._SKIP:
            self._skip_depth += 1
            return
        if tag in self._HEADINGS:
            self._flush()
            self._heading_level = self._HEADINGS[tag]
            self._heading_text = []
        elif tag in self._BLOCK:
            self._buffer.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag in self._HEADINGS and self._heading_level is not None:
            title = " ".join(" ".join(self._heading_text).split()).strip()
            level = self._heading_level
            while self._stack and self._stack[-1][0] >= level:
                self._stack.pop()
            if title:
                self._stack.append((level, title))
            self._locator = " > ".join(title for _, title in self._stack)
            self._buffer.append(title)
            self._heading_level = None

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._heading_level is not None:
            self._heading_text.append(data)
        else:
            self._buffer.append(data)

    def finish(self) -> list[Segment]:
        self._flush()
        return self.segments


class HtmlReader(BaseReader):
    """HTML/XHTML via the standard library — no external parser dependency."""

    name = "html"
    suffixes = (".html", ".htm", ".xhtml")
    media_type = MediaType.MARKUP

    def parse(self, path: Path, data: bytes) -> list[Segment]:
        extractor = _HtmlExtractor()
        extractor.feed(self.decode(data))
        extractor.close()
        return extractor.finish()
