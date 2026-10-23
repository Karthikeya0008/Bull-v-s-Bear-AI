"""Inspection CLI for the knowledge layer.

    python -m backend.query ipos
    python -m backend.query docs --ipo jio-platforms
    python -m backend.query sections --ipo jio-platforms
    python -m backend.query chunks --ipo jio-platforms --q "debt repayment" -k 5
    python -m backend.query chunks --ipo jio-platforms --section "Objects of the Issue" -k 3
    python -m backend.query tables --ipo jio-platforms [--statement pnl]

``chunks --q`` runs a dense (embedding) search; Phase 2 adds BM25 + rank fusion.
"""

from __future__ import annotations

import argparse
import sys
import textwrap
from collections import defaultdict

from sqlalchemy import func, select

from backend.db import session_scope
from backend.knowledge.models import Chunk, Document, FinancialRow, Ipo


def _short(text: str, width: int = 300) -> str:
    return textwrap.shorten(" ".join(text.split()), width=width, placeholder=" ...")


def cmd_ipos(_args) -> None:
    with session_scope() as s:
        counts = dict(s.execute(select(Chunk.ipo_id, func.count()).group_by(Chunk.ipo_id)).all())
        rows = s.scalars(select(Ipo).order_by(Ipo.status, Ipo.company)).all()
        print(f"{'ipo_id':<34} {'status':<9} {'band':<13} {'open':<11} {'listing':<11} "
              f"{'fresh cr':>9} {'ofs cr':>8} {'chunks':>7}")
        for i in rows:
            band = f"{i.price_band_low:g}-{i.price_band_high:g}" if i.price_band_high else "-"
            print(f"{i.ipo_id[:34]:<34} {i.status:<9} {band:<13} {str(i.issue_open or '-'):<11} "
                  f"{str(i.listing_date or '-'):<11} {i.fresh_issue_cr or 0:>9,.0f} "
                  f"{i.ofs_cr or 0:>8,.0f} {counts.get(i.ipo_id, 0):>7}")


def cmd_docs(args) -> None:
    with session_scope() as s:
        for d in s.scalars(select(Document).where(Document.ipo_id == args.ipo)):
            print(f"{d.doc_type:<6} filed={d.filed_date} pages={d.n_pages} chunks={d.n_chunks} "
                  f"rows={d.n_table_rows} status={d.status}\n       {d.local_path}\n"
                  f"       {d.source_url}")


def cmd_sections(args) -> None:
    with session_scope() as s:
        q = (select(Chunk.doc_id, Chunk.section, func.min(Chunk.page), func.max(Chunk.page_end),
                    func.count()).where(Chunk.ipo_id == args.ipo)
             .group_by(Chunk.doc_id, Chunk.section).order_by(Chunk.doc_id, func.min(Chunk.page)))
        types = dict(s.execute(select(Document.doc_id, Document.doc_type)).all())
        for doc_id, section, p0, p1, n in s.execute(q):
            print(f"{types.get(doc_id, '?'):<5} pp.{p0:>4}-{p1:<4} {n:>4} chunks  {section}")


def cmd_chunks(args) -> None:
    if args.q:
        from backend.knowledge.embeddings import Embedder
        from backend.knowledge.vector_store import VectorStore

        where = {"section": args.section} if args.section else None
        hits = VectorStore().query(args.ipo, Embedder().embed_query(args.q), args.k, where)
        for h in hits:
            m = h.metadata
            print(f"[{h.score:.3f}] {h.chunk_id}  ({m['doc_type']} p.{m['page']}, {m['section']})")
            print(f"    {_short(h.text)}\n")
        return
    with session_scope() as s:
        q = select(Chunk).where(Chunk.ipo_id == args.ipo)
        if args.section:
            q = q.where(Chunk.section == args.section)
        for c in s.scalars(q.order_by(Chunk.doc_id, Chunk.ordinal).limit(args.k)):
            print(f"{c.chunk_id}  (p.{c.page}-{c.page_end}, {c.section})\n    {_short(c.text)}\n")


def cmd_tables(args) -> None:
    with session_scope() as s:
        q = select(FinancialRow).where(FinancialRow.ipo_id == args.ipo)
        if args.statement:
            q = q.where(FinancialRow.statement == args.statement)
        if args.doc_type:
            q = q.join(Document).where(Document.doc_type == args.doc_type)
        rows = s.scalars(q).all()
        types = dict(s.execute(select(Document.doc_id, Document.doc_type)).all())
    grid: dict[tuple, dict[str, FinancialRow]] = defaultdict(dict)
    periods: set[str] = set()
    for r in rows:
        grid[(types[r.doc_id], r.statement, r.basis, r.line_item)][r.period] = r
        periods.add(r.period)
    cols = sorted(periods, reverse=True)
    if not grid:
        print("No financial rows.")
        return
    print(f"{'doc':<5} {'statement':<13} {'line_item':<36}" + "".join(f"{p:>14}" for p in cols)
          + "  pages   (INR million)")
    for key in sorted(grid):
        doc_type, statement, _basis, item = key
        cells = grid[key]
        pages = sorted({c.page for c in cells.values()})
        flag = "*" if any(c.is_override for c in cells.values()) else ""
        print(f"{doc_type:<5} {statement:<13} {item + flag:<36}" + "".join(
            f"{cells[p].value_inr_mn:>14,.1f}" if p in cells else f"{'-':>14}" for p in cols)
            + "  " + ",".join(map(str, pages)))


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    p = argparse.ArgumentParser(prog="python -m backend.query", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ipos").set_defaults(fn=cmd_ipos)
    for name, fn in (("docs", cmd_docs), ("sections", cmd_sections)):
        sp = sub.add_parser(name)
        sp.add_argument("--ipo", required=True)
        sp.set_defaults(fn=fn)
    sp = sub.add_parser("chunks")
    sp.add_argument("--ipo", required=True)
    sp.add_argument("--q", help="semantic query")
    sp.add_argument("--section", help="exact canonical section name")
    sp.add_argument("-k", type=int, default=5)
    sp.set_defaults(fn=cmd_chunks)
    sp = sub.add_parser("tables")
    sp.add_argument("--ipo", required=True)
    sp.add_argument("--statement", choices=["pnl", "balance_sheet", "cash_flow"])
    sp.add_argument("--doc-type", help="DRHP or RHP")
    sp.set_defaults(fn=cmd_tables)
    args = p.parse_args(argv)
    args.fn(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
