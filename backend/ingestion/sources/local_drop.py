"""Manual fallback: every PDF placed in ``data/raw/<ipo_id>/`` is treated as an offer document.

The folder name becomes the IPO id. If the IPO is not in the registry yet, the company name
is derived from the folder name (``orient-cables-india`` -> ``Orient Cables India``) and can be
corrected later in ``config/seed_ipos.yaml``.
"""

from __future__ import annotations

from pathlib import Path

from backend.ingestion.registry import detect_doc_type


def scan(raw_dir: Path) -> dict[str, list[Path]]:
    """Return ``{ipo_id: [pdf paths]}`` for every sub-folder of ``raw_dir`` holding PDFs."""
    found: dict[str, list[Path]] = {}
    if not raw_dir.exists():
        return found
    for folder in sorted(p for p in raw_dir.iterdir() if p.is_dir()):
        pdfs = sorted(p for p in folder.iterdir() if p.suffix.lower() == ".pdf")
        if pdfs:
            found[folder.name] = pdfs
    return found


def company_from_folder(ipo_id: str) -> str:
    """Best-effort display name for an IPO only known by its folder."""
    return " ".join(part.capitalize() for part in ipo_id.split("-"))


def doc_type_from_filename(path: Path) -> str:
    """Guess DRHP/RHP/... from a filename such as ``jio_drhp.pdf``; default ``DRHP``."""
    guess = detect_doc_type(path.stem.replace("_", " ").replace("-", " "))
    return guess if guess != "OTHER" else "DRHP"
