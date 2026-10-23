"""Section-aware recursive chunking with overlap.

Chunks never cross a section boundary. Inside a section the text is split recursively on
paragraph, line, sentence and word boundaries (in that order) so each chunk is at most
``chunk_size`` characters, and consecutive chunks share up to ``overlap`` characters.
The splitter works on character spans, so every chunk keeps an exact page range.
"""

from __future__ import annotations

import bisect
import hashlib
from dataclasses import dataclass

from backend.processing.pdf_parser import ParsedDoc
from backend.processing.sections import SectionStart, detect_sections, normalize_heading

SEPARATORS = ["\n\n", "\n", ". ", "; ", ", ", " "]


@dataclass
class ChunkData:
    """A chunk before it is stored: text plus the metadata every chunk must carry."""

    chunk_id: str
    section: str
    page: int
    page_end: int
    ordinal: int
    text: str


def _atomic_spans(text: str, start: int, end: int, size: int, seps: list[str]) -> list[tuple[int, int]]:
    """Split ``text[start:end]`` into spans no longer than ``size`` on the coarsest separator."""
    if end - start <= size:
        return [(start, end)]
    for i, sep in enumerate(seps):
        if text.find(sep, start, end) == -1:
            continue
        spans: list[tuple[int, int]] = []
        pos = start
        while pos < end:
            nxt = text.find(sep, pos, end)
            piece_end = end if nxt == -1 else nxt + len(sep)
            if piece_end - pos > size:
                spans.extend(_atomic_spans(text, pos, piece_end, size, seps[i + 1:]))
            else:
                spans.append((pos, piece_end))
            pos = piece_end
        return spans
    # No separator left: hard cut.
    return [(s, min(s + size, end)) for s in range(start, end, size)]


def split_spans(text: str, size: int, overlap: int,
                seps: list[str] | None = None) -> list[tuple[int, int]]:
    """Return ``(start, end)`` character spans covering ``text`` with the given size and overlap.

    Pieces are merged greedily up to ``size``; the next chunk starts on a piece boundary
    so that it repeats at most ``overlap`` characters of the previous chunk.
    """
    if size <= 0 or overlap < 0 or overlap >= size:
        raise ValueError("require 0 <= overlap < size")
    if not text:
        return []
    pieces = _atomic_spans(text, 0, len(text), size, seps or SEPARATORS)
    chunks: list[tuple[int, int]] = []
    i = 0
    while i < len(pieces):
        j = i
        while j + 1 < len(pieces) and pieces[j + 1][1] - pieces[i][0] <= size:
            j += 1
        chunks.append((pieces[i][0], pieces[j][1]))
        if j + 1 >= len(pieces):
            break
        # Step back over trailing pieces that fit inside the overlap budget, as long as the
        # next chunk can still reach the first new piece (so every chunk makes progress).
        k = j + 1
        while (k - 1 > i and pieces[j][1] - pieces[k - 1][0] <= overlap
               and pieces[j + 1][1] - pieces[k - 1][0] <= size):
            k -= 1
        i = k
    return chunks


def _section_texts(doc: ParsedDoc, starts: list[SectionStart]) -> list[tuple[str, str, list[int], list[int]]]:
    """Build one text stream per section occurrence.

    Returns ``(section, text, page_offsets, page_numbers)``; ``page_offsets[i]`` is where page
    ``page_numbers[i]`` begins inside ``text``. A page on which a new section starts is split
    at the heading line, so the text above the heading stays with the previous section.
    """
    by_page: dict[int, list[SectionStart]] = {}
    for s in starts:
        by_page.setdefault(s.page, []).append(s)

    out: list[tuple[str, str, list[int], list[int]]] = []
    current, buf, offsets, numbers = "Cover and General", "", [], []

    def flush() -> None:
        if buf.strip():
            out.append((current, buf, offsets[:], numbers[:]))

    for page in doc.pages:
        text = page.text
        for s in by_page.get(page.number, []):
            cut = _find_heading(text, s.heading)
            head, text = text[:cut], text[cut:]
            if head.strip():
                offsets.append(len(buf)); numbers.append(page.number)
                buf += head + "\n\n"
            flush()
            current, buf, offsets, numbers = s.name, "", [], []
        if text.strip():
            offsets.append(len(buf)); numbers.append(page.number)
            buf += text + "\n\n"
    flush()
    return out


def _find_heading(page_text: str, heading: str) -> int:
    """Character offset of ``heading`` in ``page_text`` (0 when it cannot be located)."""
    idx = page_text.find(heading)
    if idx >= 0:
        return idx
    target = normalize_heading(heading)
    pos = 0
    for para in page_text.split("\n\n"):
        if normalize_heading(para[:200]).startswith(target):
            return pos
        pos += len(para) + 2
    return 0


def make_chunk_id(ipo_id: str, doc_type: str, page: int, doc_id: str, ordinal: int, text: str) -> str:
    """Readable, stable id such as ``jio-platforms/DRHP/p0247/3fa9c1d2``."""
    digest = hashlib.sha1(f"{doc_id}|{ordinal}|{text}".encode()).hexdigest()[:8]
    return f"{ipo_id}/{doc_type}/p{page:04d}/{digest}"


def chunk_document(doc: ParsedDoc, ipo_id: str, doc_id: str, doc_type: str,
                   size: int, overlap: int,
                   starts: list[SectionStart] | None = None) -> list[ChunkData]:
    """Chunk a parsed document section by section."""
    starts = detect_sections(doc) if starts is None else starts
    chunks: list[ChunkData] = []
    for section, text, offsets, numbers in _section_texts(doc, starts):
        for s, e in split_spans(text, size, overlap):
            body = text[s:e].strip()
            if len(body) < 40:
                continue  # drop fragments such as stray headers
            first = numbers[max(0, bisect.bisect_right(offsets, s) - 1)]
            last = numbers[max(0, bisect.bisect_right(offsets, max(s, e - 1)) - 1)]
            ordinal = len(chunks)
            chunks.append(ChunkData(
                chunk_id=make_chunk_id(ipo_id, doc_type, first, doc_id, ordinal, body),
                section=section, page=first, page_end=last, ordinal=ordinal, text=body,
            ))
    return chunks
