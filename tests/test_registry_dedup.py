from datetime import date

from sqlalchemy import func, select

from backend.db import session_scope
from backend.ingestion.registry import (
    derive_status,
    detect_doc_type,
    issuer_from_title,
    normalize_issuer,
    record_filing,
    slugify,
)
from backend.ingestion.sources.base import FilingRecord, parse_date
from backend.ingestion.sources.nse import parse_past, parse_price_band, parse_upcoming
from backend.ingestion.sources.sebi import extract_pdf_url, parse_listing
from backend.knowledge.models import Filing, Ipo

SEBI_ROW = """<table><tr role='row' class='odd'><td>Jun 19, 2026</td><td><a href='https://www.sebi.gov.in/filings/public-issues/jun-2026/jio-platforms-ltd-drhp_102248.html' target="_blank" title="Jio Platforms Ltd - DRHP<br><a href= 'https://www.sebi.gov.in/sebi_data/commondocs/jun-2026/Jio%20Platforms%20Ltd_p.PDF'>Abridged</a>" class='points'>Jio Platforms Ltd - DRHP</a></td></tr>
<tr role='row' class='odd'><td>Oct 21, 2026</td><td><a href="https://www.sebi.gov.in/filings/public-issues/oct-2026/hunger-pangs-limited-drhp_105347.html" title="Hunger Pangs Limited � DRHP <br>">Hunger Pangs Limited � DRHP</a></td></tr></table>"""


def test_normalize_issuer_and_slug():
    assert normalize_issuer("Orient Cables (India) Ltd.") == "orient cables india"
    assert normalize_issuer("ORIENT CABLES (INDIA) LIMITED") == "orient cables india"
    assert normalize_issuer("Jio Platforms Ltd") == normalize_issuer("Jio Platforms Limited")
    assert normalize_issuer("Baanganga Gold & Diamond (I) Limited") == "baanganga gold and diamond i"
    assert slugify("jio platforms") == "jio-platforms"


def test_doc_type_and_issuer_from_title():
    assert detect_doc_type("Soleos Energy Limited – DRHP") == "DRHP"
    assert detect_doc_type("Paramotor Digital Technology Limited – UDRHP-I") == "UDRHP"
    assert detect_doc_type("Moneyview Limited - RHP") == "RHP"
    assert detect_doc_type("Tablespace Technologies Limited - Addendum to DRHP") == "ADDENDUM"
    assert issuer_from_title("Soleos Energy Limited – DRHP") == "Soleos Energy Limited"
    assert issuer_from_title("Zetwerk Manufacturing Businesses Limited : Addendum to RHP") == \
        "Zetwerk Manufacturing Businesses Limited"
    assert issuer_from_title("Grace Renewable Energy Limited- DRHP") == "Grace Renewable Energy Limited"


def test_record_filing_deduplicates_on_issuer_and_date(engine):
    a = FilingRecord("Jio Platforms Ltd", "DRHP", "sebi", "Jio Platforms Ltd - DRHP",
                     date(2026, 6, 19), page_url="https://x/page")
    b = FilingRecord("JIO PLATFORMS LIMITED", "DRHP", "seed", "", date(2026, 6, 19),
                     pdf_url="https://x/doc.pdf")
    c = FilingRecord("Jio Platforms Limited", "RHP", "sebi", "", date(2026, 10, 15))
    with session_scope(engine) as s:
        _, created_a = record_filing(s, a)
        filing_b, created_b = record_filing(s, b)
        _, created_c = record_filing(s, c)
        assert (created_a, created_b, created_c) == (True, False, True)
        assert filing_b.pdf_url == "https://x/doc.pdf"  # missing URL filled in on the duplicate
        assert s.scalar(select(func.count()).select_from(Ipo)) == 1
        assert s.scalar(select(func.count()).select_from(Filing)) == 2


def test_derive_status():
    ipo = Ipo(ipo_id="x", company="X", issuer_norm="x")
    today = date(2026, 10, 23)
    assert derive_status(ipo, today) == "upcoming"
    ipo.issue_open = date(2026, 10, 21)
    assert derive_status(ipo, today) == "open"
    ipo.listing_date = date(2026, 10, 28)
    assert derive_status(ipo, today) == "open"
    assert derive_status(ipo, date(2026, 10, 28)) == "listed"


def test_parse_sebi_listing_and_pdf_url():
    recs = parse_listing(SEBI_ROW, "Draft Offer Documents filed with SEBI")
    assert [(r.company, r.doc_type, r.filed_date) for r in recs] == [
        ("Jio Platforms Ltd", "DRHP", date(2026, 6, 19)),
        ("Hunger Pangs Limited", "DRHP", date(2026, 10, 21)),
    ]
    page = ("<iframe src='../../../web/?file=https://www.sebi.gov.in/sebi_data/attachdocs/"
            "jun-2026/1781870482419.PDF' width='100%'>")
    assert extract_pdf_url(page) == \
        "https://www.sebi.gov.in/sebi_data/attachdocs/jun-2026/1781870482419.PDF"


def test_parse_nse_payloads():
    assert parse_price_band("Rs.1065 to Rs.1119") == (1065.0, 1119.0)
    assert parse_price_band("   151") == (151.0, 151.0)
    up = parse_upcoming([{"companyName": "Jio Platforms Limited", "issueStartDate": "21-Oct-2026",
                          "issueEndDate": "23-Oct-2026", "issuePrice": "Rs.1065 to Rs.1119",
                          "series": "EQ", "symbol": "JPL"},
                         {"companyName": "Tiny SME Ltd", "series": "SME", "issuePrice": "Rs.50"}])
    assert len(up) == 1 and up[0].extra["issue_open"] == date(2026, 10, 21)
    past = parse_past([{"company": "Zetwerk Manufacturing Businesses Limited",
                        "listingDate": "23-OCT-2026", "priceRange": "Rs.143 to Rs.151",
                        "securityType": "EQ", "symbol": "ZETWERK"},
                       {"company": "Old Co", "listingDate": "01-JAN-2020", "securityType": "EQ"}],
                      since=date(2026, 9, 1))
    assert [r.company for r in past] == ["Zetwerk Manufacturing Businesses Limited"]
    assert past[0].extra["listing_date"] == date(2026, 10, 23)


def test_parse_date_formats():
    assert parse_date("Jun 19, 2026") == date(2026, 6, 19)
    assert parse_date("23-OCT-2026") == date(2026, 10, 23)
    assert parse_date("2026-10-15") == date(2026, 10, 15)
    assert parse_date("not a date") is None
