"""Ingestion CLI.

    python -m backend.ingest --ipo jio-platforms     # one IPO
    python -m backend.ingest --all                   # every IPO with documents
    python -m backend.ingest --watch                 # run the watcher once (no ingest)
    python -m backend.ingest --schedule              # keep watching on an interval

Options: --force (re-ingest parsed docs), --no-embed, --no-tables, --no-download.
"""

from __future__ import annotations

import argparse
import logging
import sys

from backend.config import get_settings
from backend.db import session_scope
from backend.ingestion import watcher
from backend.ingestion.downloader import download_filings
from backend.ingestion.pipeline import documents_for, ingest_document
from backend.knowledge.models import Ipo

log = logging.getLogger("backend.ingest")


def build_parser() -> argparse.ArgumentParser:
    """Command-line interface definition."""
    p = argparse.ArgumentParser(prog="python -m backend.ingest", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    target = p.add_mutually_exclusive_group(required=True)
    target.add_argument("--ipo", help="ipo_id to ingest, e.g. jio-platforms")
    target.add_argument("--all", action="store_true", help="ingest every IPO with documents")
    target.add_argument("--watch", action="store_true", help="run the IPO watcher once")
    target.add_argument("--schedule", action="store_true", help="run the watcher on a schedule")
    p.add_argument("--force", action="store_true", help="re-ingest already parsed documents")
    p.add_argument("--no-embed", action="store_true", help="skip embeddings / ChromaDB")
    p.add_argument("--no-tables", action="store_true", help="skip financial table extraction")
    p.add_argument("--no-download", action="store_true", help="do not download filings")
    p.add_argument("--offline", action="store_true",
                   help="skip network sources; only seed file and data/raw drop folder")
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    """Entry point; returns a process exit code."""
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                        datefmt="%H:%M:%S")
    for noisy in ("httpx", "httpcore", "chromadb", "sentence_transformers", "pdfminer"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    if args.schedule:
        watcher.run_scheduled()
        return 0

    report = watcher.run_once(sources=[] if args.offline else None)
    if args.watch:
        print(f"Fetched: {report.fetched}")
        print(f"New filings: {len(report.new_filings)}")
        for title in report.new_filings[:50]:
            print(f"  + {title}")
        print(f"New local PDFs: {len(report.local_docs)}")
        return 0

    settings = get_settings()
    with session_scope() as session:
        if args.ipo and session.get(Ipo, args.ipo) is None:
            print(f"Unknown ipo_id {args.ipo!r}. Known: "
                  + ", ".join(i.ipo_id for i in watcher.list_ipos(session)[:30]))
            return 2
        if not args.no_download:
            # The SEBI feed lists dozens of DRHPs (~10-20 MB each), so --all only downloads
            # the curated IPOs from seed_ipos.yaml; any other IPO is fetched with --ipo.
            targets = [args.ipo] if args.ipo else [
                i.ipo_id for i in watcher.list_ipos(session) if i.source == "seed"]
            for ipo_id in targets:
                download_filings(session, settings.raw_dir, ipo_id)
        watcher.scan_local(session, watcher.WatchReport())
        docs = documents_for(session, args.ipo, args.force)
        if not docs:
            print("Nothing to ingest (use --force to re-ingest parsed documents).")
            return 0
        failures = 0
        for doc in docs:
            try:
                r = ingest_document(session, doc, embed=not args.no_embed,
                                    extract_tables=not args.no_tables)
                session.commit()
                print(f"OK  {doc.ipo_id:<24} {doc.doc_type:<5} pages={r.pages:<4} "
                      f"sections={r.sections:<3} chunks={r.chunks:<5} rows={r.table_rows:<4} "
                      f"{r.seconds:.0f}s")
            except Exception as exc:  # keep going with the other documents
                session.rollback()
                log.exception("Failed to ingest %s", doc.local_path)
                doc = session.merge(doc)
                doc.status, doc.error = "failed", str(exc)[:2000]
                session.commit()
                failures += 1
                print(f"ERR {doc.ipo_id:<24} {doc.local_path}: {exc}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
