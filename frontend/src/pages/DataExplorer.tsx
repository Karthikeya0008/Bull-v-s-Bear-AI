import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import CitationModal from "../components/CitationModal";
import { fmtDate, fmtMetric, fmtNum } from "../format";
import type { ChunkPage, EmbeddingStatus, FinancialRowData, Ipo, Metric } from "../types";

type Tab = "documents" | "chunks" | "financials" | "metrics";
const TABS: { key: Tab; label: string; table: string }[] = [
  { key: "documents", label: "Documents", table: "documents" },
  { key: "chunks", label: "Embedded chunks", table: "chunks" },
  { key: "financials", label: "Financial rows", table: "financial_rows" },
  { key: "metrics", label: "Metrics", table: "metrics" },
];
const PAGE_SIZE = 50;

export default function DataExplorer() {
  const { ipoId = "" } = useParams();
  const [tab, setTab] = useState<Tab>("documents");
  const [ipo, setIpo] = useState<Ipo | null>(null);
  const [status, setStatus] = useState<EmbeddingStatus[]>([]);
  const [docId, setDocId] = useState("");
  const [metrics, setMetrics] = useState<Metric[]>([]);
  const [cite, setCite] = useState<string | null>(null);

  useEffect(() => {
    api.ipo(ipoId).then((i) => { setIpo(i); setDocId(i.documents?.[0]?.doc_id ?? ""); });
    api.embeddingStatus(ipoId).then(setStatus).catch(() => setStatus([]));
    api.metrics(ipoId).then(setMetrics).catch(() => setMetrics([]));
  }, [ipoId]);

  const metricMap = useMemo(() => Object.fromEntries(metrics.map((m) => [m.metric_id, m])), [metrics]);
  if (!ipo) return <div className="text-sm text-slate-500">Loading…</div>;
  const docs = ipo.documents ?? [];

  return (
    <div className="space-y-6">
      <Link to={`/ipo/${ipoId}`} className="inline-flex items-center gap-1 text-sm font-medium text-slate-500 hover:text-brand">
        ← {ipo.company}
      </Link>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Data Explorer</h1>
          <p className="mt-1 text-sm text-slate-600">
            The SQLite records behind {ipo.company}: every document, every chunk embedded into ChromaDB, every
            extracted financial figure and every computed metric.
          </p>
        </div>
        {(tab === "chunks" || tab === "financials") && docs.length > 1 && (
          <label className="flex items-center gap-2 text-sm text-slate-600">
            Document
            <select value={docId} onChange={(e) => setDocId(e.target.value)}
              className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm outline-none focus:border-brand">
              {docs.map((d) => <option key={d.doc_id} value={d.doc_id}>{d.doc_type} · filed {fmtDate(d.filed_date)}</option>)}
            </select>
          </label>
        )}
      </div>

      <div className="flex flex-wrap gap-1 border-b border-slate-200">
        {TABS.map((t) => (
          <button key={t.key} onClick={() => setTab(t.key)}
            className={`-mb-px border-b-2 px-4 py-2 text-sm font-medium transition ${
              tab === t.key ? "border-brand text-brand" : "border-transparent text-slate-500 hover:text-slate-800"}`}>
            {t.label} <span className="ml-1 font-mono text-[11px] text-slate-400">{t.table}</span>
          </button>
        ))}
      </div>

      {tab === "documents" && <DocumentsTab ipo={ipo} status={status} />}
      {tab === "chunks" && docId && <ChunksTab ipoId={ipoId} docId={docId} onOpen={setCite} />}
      {tab === "financials" && docId && <FinancialsTab ipoId={ipoId} docId={docId} />}
      {tab === "metrics" && <MetricsTab metrics={metrics} onOpen={setCite} />}
      <CitationModal refId={cite} metrics={metricMap} onClose={() => setCite(null)} />
    </div>
  );
}

function DocumentsTab({ ipo, status }: { ipo: Ipo; status: EmbeddingStatus[] }) {
  const byDoc = Object.fromEntries(status.map((s) => [s.doc_id, s]));
  return (
    <div className="card overflow-x-auto p-0">
      <table className="w-full text-sm">
        <thead className="table-head">
          <tr>
            <th className="px-4 py-2.5">Type</th><th className="px-4 py-2.5">Filed</th>
            <th className="px-4 py-2.5 text-right">Pages</th><th className="px-4 py-2.5 text-right">Table rows</th>
            <th className="px-4 py-2.5 text-right">SQLite chunks</th><th className="px-4 py-2.5 text-right">ChromaDB vectors</th>
            <th className="px-4 py-2.5">Vector DB</th><th className="px-4 py-2.5">Status</th><th className="px-4 py-2.5">Source</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {(ipo.documents ?? []).map((d) => {
            const st = byDoc[d.doc_id];
            return (
              <tr key={d.doc_id} className="hover:bg-slate-50">
                <td className="px-4 py-3">
                  <div className="font-semibold text-slate-900">{d.doc_type}</div>
                  <div className="font-mono text-[11px] text-slate-400" title={d.doc_id}>sha256 {d.doc_id.slice(0, 12)}…</div>
                </td>
                <td className="whitespace-nowrap px-4 py-3 text-slate-600">{fmtDate(d.filed_date)}</td>
                <td className="px-4 py-3 text-right tabular-nums">{fmtNum(d.pages, 0)}</td>
                <td className="px-4 py-3 text-right tabular-nums">{fmtNum(d.table_rows, 0)}</td>
                <td className="px-4 py-3 text-right tabular-nums">{fmtNum(st?.sqlite_chunks ?? d.chunks, 0)}</td>
                <td className="px-4 py-3 text-right tabular-nums">{st ? fmtNum(st.vectors, 0) : "…"}</td>
                <td className="px-4 py-3">
                  {st && (st.in_sync
                    ? <span className="chip border-emerald-200 bg-emerald-50 text-emerald-700">✓ In sync</span>
                    : <span className="chip border-rose-200 bg-rose-50 text-rose-700">✕ Mismatch</span>)}
                  {st && <div className="mt-0.5 font-mono text-[11px] text-slate-400">{st.collection} · {st.embedding_model}</div>}
                </td>
                <td className="px-4 py-3"><span className="chip border-slate-200 bg-slate-50 capitalize text-slate-600">{d.status}</span></td>
                <td className="whitespace-nowrap px-4 py-3 text-xs">
                  <a className="text-brand hover:underline" href={`/api/documents/${d.doc_id}/pdf`} target="_blank" rel="noreferrer">PDF</a>
                  {d.source_url?.startsWith("http") && <> · <a className="text-brand hover:underline" href={d.source_url} target="_blank" rel="noreferrer">SEBI</a></>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function ChunksTab({ ipoId, docId, onOpen }: { ipoId: string; docId: string; onOpen: (id: string) => void }) {
  const [section, setSection] = useState("");
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<ChunkPage | null>(null);

  useEffect(() => { setOffset(0); }, [docId, section, search]);
  useEffect(() => {
    const t = setTimeout(() => setSearch(query), 300);
    return () => clearTimeout(t);
  }, [query]);
  useEffect(() => {
    api.chunks(ipoId, { doc_id: docId, section, q: search, offset, limit: PAGE_SIZE }).then(setData);
  }, [ipoId, docId, section, search, offset]);

  const total = data?.total ?? 0;
  return (
    <div className="card p-0">
      <div className="flex flex-wrap items-center gap-3 border-b border-slate-200 px-4 py-3">
        <select value={section} onChange={(e) => setSection(e.target.value)}
          className="w-56 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm outline-none focus:border-brand">
          <option value="">All sections</option>
          {data?.sections.map((s) => <option key={s.section} value={s.section}>{s.section} ({s.count})</option>)}
        </select>
        <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search chunk text…"
          className="w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm outline-none focus:border-brand focus:ring-2 focus:ring-brand/15 sm:w-72" />
        <span className="ml-auto text-sm text-slate-500">
          {total ? `${offset + 1}–${Math.min(offset + PAGE_SIZE, total)} of ${fmtNum(total, 0)} chunks` : "No chunks"}
        </span>
        <button className="btn-secondary py-1.5" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>← Prev</button>
        <button className="btn-secondary py-1.5" disabled={offset + PAGE_SIZE >= total} onClick={() => setOffset(offset + PAGE_SIZE)}>Next →</button>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="table-head">
            <tr>
              <th className="px-4 py-2.5">#</th><th className="px-4 py-2.5">Chunk id</th><th className="px-4 py-2.5">Section</th>
              <th className="px-4 py-2.5">Pages</th><th className="px-4 py-2.5 text-right">Chars</th><th className="px-4 py-2.5">Text</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {data?.items.map((c) => (
              <tr key={c.chunk_id} onClick={() => onOpen(c.chunk_id)} className="cursor-pointer align-top hover:bg-brand-light/50">
                <td className="px-4 py-2.5 tabular-nums text-slate-400">{c.ordinal}</td>
                <td className="whitespace-nowrap px-4 py-2.5 font-mono text-[11px] text-slate-600">{c.chunk_id}</td>
                <td className="whitespace-nowrap px-4 py-2.5 text-slate-700">{c.section}</td>
                <td className="whitespace-nowrap px-4 py-2.5 text-slate-600">p.{c.page}{c.page_end !== c.page ? `–${c.page_end}` : ""}</td>
                <td className="px-4 py-2.5 text-right tabular-nums text-slate-500">{c.chars}</td>
                <td className="max-w-xl px-4 py-2.5 text-slate-700">
                  <div className="line-clamp-2">{c.text}</div>
                </td>
              </tr>
            ))}
            {data && !data.items.length && <tr><td colSpan={6} className="px-4 py-10 text-center text-slate-500">No chunks match.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function FinancialsTab({ ipoId, docId }: { ipoId: string; docId: string }) {
  const [rows, setRows] = useState<FinancialRowData[] | null>(null);
  const [statement, setStatement] = useState("");
  useEffect(() => { setRows(null); api.financials(ipoId, docId).then(setRows); }, [ipoId, docId]);

  const shown = (rows ?? []).filter((r) => !statement || r.statement === statement)
    .sort((a, b) => a.statement.localeCompare(b.statement) || a.line_item.localeCompare(b.line_item) || b.period.localeCompare(a.period));
  return (
    <div className="card p-0">
      <div className="flex flex-wrap items-center gap-3 border-b border-slate-200 px-4 py-3">
        <div className="inline-flex rounded-lg border border-slate-200 bg-slate-50 p-0.5">
          {[["", "All"], ["pnl", "P&L"], ["balance_sheet", "Balance sheet"], ["cash_flow", "Cash flow"]].map(([k, l]) => (
            <button key={k} onClick={() => setStatement(k)}
              className={`rounded-md px-3 py-1.5 text-sm font-medium ${statement === k ? "bg-white text-slate-900 shadow-card" : "text-slate-500"}`}>{l}</button>
          ))}
        </div>
        <span className="ml-auto text-sm text-slate-500">{shown.length} rows · values in ₹ million (EPS in ₹)</span>
      </div>
      <div className="max-h-[65vh] overflow-auto">
        <table className="w-full text-sm">
          <thead className="table-head sticky top-0">
            <tr>
              <th className="px-4 py-2.5">Statement</th><th className="px-4 py-2.5">Line item</th><th className="px-4 py-2.5">Period</th>
              <th className="px-4 py-2.5 text-right">Value</th><th className="px-4 py-2.5">Label in document</th><th className="px-4 py-2.5">Page</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {shown.map((r, i) => (
              <tr key={i} className="hover:bg-slate-50">
                <td className="whitespace-nowrap px-4 py-2 text-slate-500">{r.statement}</td>
                <td className="whitespace-nowrap px-4 py-2 font-mono text-[12px] text-slate-800">
                  {r.line_item}{r.is_override ? <span className="chip ml-1 border-amber-200 bg-amber-50 text-amber-700">override</span> : null}
                </td>
                <td className="whitespace-nowrap px-4 py-2 text-slate-600">{r.period}</td>
                <td className="whitespace-nowrap px-4 py-2 text-right tabular-nums font-medium">{fmtNum(r.value_inr_mn)}</td>
                <td className="px-4 py-2 text-slate-600">{r.raw_label}</td>
                <td className="px-4 py-2">
                  <a className="text-brand hover:underline" href={`/api/documents/${docId}/pdf#page=${r.page}`} target="_blank" rel="noreferrer">p.{r.page}</a>
                </td>
              </tr>
            ))}
            {rows && !shown.length && <tr><td colSpan={6} className="px-4 py-10 text-center text-slate-500">No rows.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function MetricsTab({ metrics, onOpen }: { metrics: Metric[]; onOpen: (id: string) => void }) {
  return (
    <div className="card overflow-x-auto p-0">
      <table className="w-full text-sm">
        <thead className="table-head">
          <tr>
            <th className="px-4 py-2.5">Metric id</th><th className="px-4 py-2.5">Label</th><th className="px-4 py-2.5 text-right">Value</th>
            <th className="px-4 py-2.5">Formula</th><th className="px-4 py-2.5">Pages</th><th className="px-4 py-2.5">Status</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {metrics.map((m) => (
            <tr key={m.metric_id} onClick={() => onOpen(m.metric_id)} className="cursor-pointer align-top hover:bg-brand-light/50">
              <td className="whitespace-nowrap px-4 py-2.5 font-mono text-[11px] text-slate-600">{m.metric_id}</td>
              <td className="whitespace-nowrap px-4 py-2.5 text-slate-800">{m.label}</td>
              <td className="whitespace-nowrap px-4 py-2.5 text-right tabular-nums font-medium">{fmtMetric(m.value, m.unit)}</td>
              <td className="max-w-md px-4 py-2.5 font-mono text-[11px] text-slate-500">{m.formula}</td>
              <td className="whitespace-nowrap px-4 py-2.5 text-slate-600">{m.source_pages.length ? m.source_pages.join(", ") : "registry"}</td>
              <td className="px-4 py-2.5">
                <span className={`chip ${m.status === "ok" ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-slate-200 bg-slate-50 text-slate-500"}`}>{m.status}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
