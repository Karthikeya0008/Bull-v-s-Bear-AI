import pytest

from backend.processing.chunker import chunk_document, split_spans
from backend.processing.pdf_parser import parse_pdf

TEXT = "\n\n".join(
    f"Paragraph {i}. " + " ".join(f"sentence {i}.{j} has several words in it." for j in range(6))
    for i in range(30)
)


@pytest.mark.parametrize("size,overlap", [(300, 50), (500, 100), (1200, 200), (80, 0)])
def test_split_spans_bounds_coverage_and_overlap(size, overlap):
    spans = split_spans(TEXT, size, overlap)
    assert spans[0][0] == 0 and spans[-1][1] == len(TEXT)
    for (s, e) in spans:
        assert 0 < e - s <= size
    for (s0, e0), (s1, e1) in zip(spans, spans[1:]):
        assert s1 > s0 and e1 > e0, "every chunk must make progress"
        assert s1 <= e0, "no gaps between chunks"
        assert e0 - s1 <= overlap, "overlap never exceeds the budget"


def test_split_spans_prefers_paragraph_boundaries():
    spans = split_spans(TEXT, 600, 0)
    # Every chunk except possibly the last should end right after a paragraph break.
    assert all(TEXT[e - 2:e] == "\n\n" for _, e in spans[:-1])


def test_split_spans_short_text_and_validation():
    assert split_spans("short text", 100, 10) == [(0, 10)]
    assert split_spans("", 100, 10) == []
    with pytest.raises(ValueError):
        split_spans("abc", 10, 10)


def test_split_spans_hard_cut_without_separators():
    spans = split_spans("x" * 250, 100, 0)
    assert spans == [(0, 100), (100, 200), (200, 250)]


def test_chunk_document_respects_sections_and_pages(drhp_pdf):
    parsed = parse_pdf(drhp_pdf)
    chunks = chunk_document(parsed, "acme", "doc123", "DRHP", size=600, overlap=100)
    assert chunks, "expected chunks"
    by_section = {}
    for c in chunks:
        by_section.setdefault(c.section, []).append(c)
        assert c.page <= c.page_end
        assert c.chunk_id.startswith(f"acme/DRHP/p{c.page:04d}/")
    assert set(by_section) >= {"Risk Factors", "Objects of the Issue", "Financial Information",
                               "Outstanding Litigation"}
    risk_pages = {p for c in by_section["Risk Factors"] for p in (c.page, c.page_end)}
    assert risk_pages <= {3, 4, 5}
    # Text above the heading on page 5 belongs to Risk Factors, not Objects of the Issue.
    assert any("spectrum renewal" in c.text for c in by_section["Risk Factors"])
    assert not any("spectrum renewal" in c.text for c in by_section["Objects of the Issue"])
    objects = by_section["Objects of the Issue"]
    assert all(c.page == 5 for c in objects)
    assert "repayment or prepayment of borrowings" in objects[0].text


def test_chunk_ids_are_unique_and_stable(drhp_pdf):
    parsed = parse_pdf(drhp_pdf)
    a = chunk_document(parsed, "acme", "doc123", "DRHP", size=600, overlap=100)
    b = chunk_document(parsed, "acme", "doc123", "DRHP", size=600, overlap=100)
    assert [c.chunk_id for c in a] == [c.chunk_id for c in b]
    assert len({c.chunk_id for c in a}) == len(a)
