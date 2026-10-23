from backend.processing.pdf_parser import parse_pdf
from backend.processing.sections import (
    SectionStart,
    collapse,
    detect_sections,
    match_heading,
    normalize_heading,
    section_for_page,
)


def test_normalize_heading_strips_prefix_leaders_and_page_numbers():
    assert normalize_heading("SECTION II: RISK FACTORS") == "risk factors"
    assert normalize_heading("OBJECTS OF THE OFFER ........ 112") == "objects of the offer"
    assert normalize_heading("MANAGEMENT’S DISCUSSION AND ANALYSIS") == \
        "management's discussion and analysis"


def test_match_heading_variants():
    assert match_heading("OBJECTS OF THE OFFER") == "Objects of the Issue"
    assert match_heading("Objects of the Issue") == "Objects of the Issue"
    assert match_heading("SECTION II - RISK FACTORS") == "Risk Factors"
    assert match_heading("OUTSTANDING LITIGATION AND MATERIAL DEVELOPMENTS") == \
        "Outstanding Litigation"
    assert match_heading("RESTATED CONSOLIDATED FINANCIAL INFORMATION") == "Financial Information"
    assert match_heading(
        "MANAGEMENT'S DISCUSSION AND ANALYSIS OF FINANCIAL CONDITION AND RESULTS OF OPERATIONS"
    ) == "Management's Discussion and Analysis"


def test_match_heading_rejects_body_text():
    assert match_heading("Risk factors relating to our business are described below") is None
    assert match_heading("Business") is None
    assert match_heading("x" * 200) is None


def test_collapse_drops_running_header_repeats():
    starts = [SectionStart(3, "Risk Factors", "RISK FACTORS"),
              SectionStart(4, "Risk Factors", "RISK FACTORS"),
              SectionStart(9, "Our Business", "OUR BUSINESS")]
    assert [(s.page, s.name) for s in collapse(starts)] == [(3, "Risk Factors"), (9, "Our Business")]


def test_section_for_page():
    starts = [SectionStart(3, "Risk Factors", ""), SectionStart(9, "Our Business", "")]
    assert section_for_page(starts, 1) == "Cover and General"
    assert section_for_page(starts, 3) == "Risk Factors"
    assert section_for_page(starts, 8) == "Risk Factors"
    assert section_for_page(starts, 50) == "Our Business"


def test_detect_sections_on_pdf_ignores_table_of_contents(drhp_pdf):
    parsed = parse_pdf(drhp_pdf)
    starts = detect_sections(parsed)
    assert [(s.page, s.name) for s in starts] == [
        (3, "Risk Factors"),
        (5, "Objects of the Issue"),
        (6, "Financial Information"),
        (7, "Outstanding Litigation"),
    ]
