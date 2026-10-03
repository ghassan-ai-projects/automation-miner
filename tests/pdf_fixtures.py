"""Hand-assembled PDFs so tests need no PDF writer dependency."""

from __future__ import annotations


def make_pdf(pages: list[str]) -> bytes:
    """Minimal valid PDF with extractable text, one page per entry."""
    font = 3 + 2 * len(pages)
    objs: dict[int, bytes] = {
        1: b"<</Type/Catalog/Pages 2 0 R>>",
        font: b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    }
    kids = []
    for i, text in enumerate(pages):
        page, content = 3 + 2 * i, 4 + 2 * i
        kids.append(f"{page} 0 R")
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
        objs[page] = (
            f"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents {content} 0 R"
            f"/Resources<</Font<</F1 {font} 0 R>>>>>>"
        ).encode()
        objs[content] = b"<</Length %d>>\nstream\n%s\nendstream" % (len(stream), stream)
    objs[2] = ("<</Type/Pages/Kids[" + " ".join(kids) + f"]/Count {len(pages)}>>").encode()

    out = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for num in sorted(objs):
        offsets[num] = len(out)
        out += f"{num} 0 obj\n".encode() + objs[num] + b"\nendobj\n"
    xref, top = len(out), max(objs)
    out += f"xref\n0 {top + 1}\n".encode() + b"0000000000 65535 f \n"
    for num in range(1, top + 1):
        out += (
            f"{offsets[num]:010d} 00000 n \n".encode()
            if num in offsets
            else b"0000000000 65535 f \n"
        )
    out += f"trailer\n<</Size {top + 1}/Root 1 0 R>>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)
