"""PDF text extraction with PyMuPDF, keeping page numbers and font information for headings."""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf as fitz  # PyMuPDF


@dataclass
class Line:
    """One visual line of text with the font metrics used for heading detection."""

    text: str
    size: float
    bold: bool
    y0: float  # distance from the top of the page, as a fraction of page height (0..1)


@dataclass
class Page:
    """Text of one physical PDF page (``number`` is 1-based, matching PDF viewers)."""

    number: int
    text: str
    lines: list[Line] = field(default_factory=list)


@dataclass
class ParsedDoc:
    """A parsed PDF: pages, bookmarks (outline) and the dominant body font size."""

    path: Path
    pages: list[Page]
    toc: list[tuple[int, str, int]]  # (level, title, 1-based page)
    body_font_size: float

    @property
    def n_pages(self) -> int:
        return len(self.pages)


_PAGE_NUMBER_LINE = re.compile(r"^\s*(?:page\s*)?\d{1,4}\s*$", re.IGNORECASE)


def _clean_line(text: str) -> str:
    return re.sub(r"[ \t ]+", " ", text).strip()


def _join_block(lines: list[str]) -> str:
    """Join the lines of a text block into a paragraph, repairing hyphenated line breaks."""
    out = ""
    for ln in lines:
        if not out:
            out = ln
        elif out.endswith("-") and ln[:1].islower():
            out = out[:-1] + ln
        else:
            out += " " + ln
    return out


def parse_pdf(path: Path) -> ParsedDoc:
    """Extract per-page text (paragraphs separated by blank lines) and line font metadata.

    Bare page-number lines are dropped so they do not pollute chunks.
    """
    doc = fitz.open(path)
    if doc.page_count == 0:
        doc.close()
        raise ValueError(f"{path} has no readable pages (truncated or corrupt PDF?)")
    pages: list[Page] = []
    sizes: list[float] = []
    try:
        for index, pg in enumerate(doc):
            height = pg.rect.height or 1.0
            data = pg.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
            paragraphs: list[str] = []
            lines: list[Line] = []
            for block in data.get("blocks", []):
                if block.get("type") != 0:
                    continue  # image block
                block_lines: list[str] = []
                for ln in block.get("lines", []):
                    spans = [s for s in ln.get("spans", []) if s.get("text", "").strip()]
                    if not spans:
                        continue
                    text = _clean_line("".join(s["text"] for s in spans))
                    if not text or _PAGE_NUMBER_LINE.match(text):
                        continue
                    size = max(s["size"] for s in spans)
                    bold = all((s["flags"] & 16) or "bold" in s["font"].lower() for s in spans)
                    lines.append(Line(text, round(size, 1), bool(bold), ln["bbox"][1] / height))
                    sizes.append(round(size, 1))
                    block_lines.append(text)
                if block_lines:
                    paragraphs.append(_join_block(block_lines))
            pages.append(Page(index + 1, "\n\n".join(paragraphs), lines))
        toc = [(lvl, _clean_line(title), page) for lvl, title, page, *_ in doc.get_toc(simple=True)
               if page >= 1]
    finally:
        doc.close()
    body = statistics.median(sizes) if sizes else 10.0
    return ParsedDoc(path=path, pages=pages, toc=toc, body_font_size=body)
