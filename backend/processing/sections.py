"""Map DRHP/RHP headings to canonical section names and find where each section starts.

SEBI's ICDR Regulations fix the order and titles of offer-document sections, so a small
pattern table covers almost every Indian IPO. Two strategies are used:

1. PDF bookmarks (outline), when the file has them - exact and cheap.
2. Otherwise, a heading scan: lines that are larger or bolder than body text, sit in the top
   part of the page and fully match a known heading. Pages that match many headings at once
   are tables of contents and are ignored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from backend.processing.pdf_parser import ParsedDoc

DEFAULT_SECTION = "Cover and General"

# (canonical name, regex that must fully match the normalised heading)
SECTION_PATTERNS: list[tuple[str, str]] = [
    ("Definitions and Abbreviations", r"definitions and abbreviations"),
    ("Presentation of Financial Information",
     r"certain conventions.*|presentation of financial.*|currency of presentation.*"),
    ("Forward-Looking Statements", r"forward[- ]looking statements"),
    ("Offer Document Summary",
     r"(summary of (the )?(draft )?(red herring )?(offer document|prospectus))|"
     r"((draft )?(red herring )?offer document summary)|(prospectus summary)"),
    ("Risk Factors", r"risk factors"),
    ("The Offer", r"the (offer|issue)"),
    ("Summary of Financial Information",
     r"summary (of )?(restated )?(consolidated )?financial (information|statements)"),
    ("General Information", r"general information"),
    ("Capital Structure", r"capital structure"),
    ("Objects of the Issue", r"objects? of the (offer|issue)"),
    ("Basis for Offer Price", r"basis (for|of) (the )?(offer|issue) price"),
    ("Statement of Special Tax Benefits", r"statement of (possible )?special tax benefits.*"),
    ("Industry Overview", r"industry overview"),
    ("Our Business", r"our business"),
    ("Key Regulations and Policies", r"key (industry )?regulations and policies.*"),
    ("History and Corporate Matters", r"history and certain corporate matters"),
    ("Our Subsidiaries", r"our (subsidiaries|subsidiary)"),
    ("Our Management", r"our management"),
    ("Promoters and Promoter Group", r"our promoters? and (the )?promoter group"),
    ("Group Companies", r"(our )?group compan(y|ies)"),
    ("Dividend Policy", r"dividend policy"),
    ("Financial Information",
     r"financial (information|statements)|restated (consolidated |standalone )?financial "
     r"(information|statements)"),
    ("Other Financial Information", r"other financial information"),
    ("Related Party Transactions", r"related party transactions"),
    ("Capitalisation Statement", r"capitali[sz]ation statement"),
    ("Financial Indebtedness", r"financial indebtedness"),
    ("Management's Discussion and Analysis",
     r"management'?s discussion and analysis of financial (condition|position).*"),
    ("Outstanding Litigation", r"outstanding litigation(s)? and (other )?material developments"),
    ("Government and Other Approvals", r"government and other approvals"),
    ("Other Regulatory Disclosures", r"other regulatory and statutory disclosures"),
    ("Terms of the Offer", r"terms of the (offer|issue)"),
    ("Offer Structure", r"(offer|issue) structure"),
    ("Offer Procedure", r"(offer|issue) procedure"),
    ("Restrictions on Foreign Ownership",
     r"restrictions on foreign ownership of indian securities"),
    ("Articles of Association", r"(description of equity shares and terms of )?"
     r"(the )?(main provisions of )?(the )?articles of association.*"),
    ("Material Contracts", r"material contracts and documents for inspection"),
    ("Declaration", r"declaration"),
]

_COMPILED = [(name, re.compile(rf"^(?:{pat})$")) for name, pat in SECTION_PATTERNS]
_SECTION_PREFIX = re.compile(r"^section\s+[ivxlc\d]+\s*[:.\-–—]?\s*", re.IGNORECASE)


@dataclass(frozen=True)
class SectionStart:
    """Where a canonical section begins: physical page plus the heading text found there."""

    page: int
    name: str
    heading: str


def normalize_heading(text: str) -> str:
    """Lowercase, drop ``SECTION IV:`` prefixes, dot leaders and trailing page numbers."""
    t = text.replace("’", "'").replace("‘", "'")
    t = _SECTION_PREFIX.sub("", t.strip())
    t = re.sub(r"\.{3,}.*$", "", t)  # TOC dot leaders
    t = re.sub(r"\s+\d{1,4}$", "", t)  # trailing page number
    t = re.sub(r"[^a-zA-Z' ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip().lower()


def match_heading(text: str) -> str | None:
    """Return the canonical section name if ``text`` is a known DRHP heading, else ``None``."""
    if len(text) > 160:
        return None
    norm = normalize_heading(text)
    if not norm:
        return None
    for name, rx in _COMPILED:
        if rx.match(norm):
            return name
    return None


def is_upper_heading(text: str, min_ratio: float = 0.85) -> bool:
    """DRHP section headings are set in capitals; sentences that mention a section are not."""
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and sum(c.isupper() for c in letters) / len(letters) >= min_ratio


def _from_toc(doc: ParsedDoc) -> list[SectionStart]:
    starts = []
    for _level, title, page in doc.toc:
        name = match_heading(title)
        if name:
            starts.append(SectionStart(page, name, title))
    return starts


def _from_headings(doc: ParsedDoc, max_y: float = 0.35) -> list[SectionStart]:
    body = doc.body_font_size
    starts: list[SectionStart] = []
    for page in doc.pages:
        hits = []
        for ln in page.lines:
            if ln.y0 > max_y:
                continue
            emphasised = ln.size >= body * 1.08 or ln.bold
            if not emphasised or not is_upper_heading(ln.text):
                continue
            name = match_heading(ln.text)
            if name:
                hits.append(SectionStart(page.number, name, ln.text))
        if len({h.name for h in hits}) > 3:
            continue  # table of contents or index page
        starts.extend(hits[:1])
    return starts


def collapse(starts: list[SectionStart]) -> list[SectionStart]:
    """Sort by page and drop consecutive repeats (running headers repeat the same section)."""
    out: list[SectionStart] = []
    for s in sorted(starts, key=lambda s: s.page):
        if out and out[-1].name == s.name:
            continue
        if out and out[-1].page == s.page:
            out[-1] = s  # two headings on one page: the later (more specific) one wins
            continue
        out.append(s)
    return out


def detect_sections(doc: ParsedDoc, min_toc_hits: int = 5) -> list[SectionStart]:
    """Return section start points, preferring bookmarks and falling back to a heading scan."""
    toc = _from_toc(doc)
    if len({s.name for s in toc}) >= min_toc_hits:
        return collapse(toc)
    return collapse(_from_headings(doc))


def section_for_page(starts: list[SectionStart], page: int) -> str:
    """Return the section that a page belongs to."""
    current = DEFAULT_SECTION
    for s in starts:
        if s.page > page:
            break
        current = s.name
    return current
