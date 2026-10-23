import { useEffect, useState } from "react";
import { api } from "../api";
import { fmtMetric, fmtNum } from "../format";
import type { ChunkDetail, Metric } from "../types";

interface Props {
  refId: string | null;
  metrics: Record<string, Metric>;
  onClose: () => void;
}

export default function CitationModal({ refId, metrics, onClose }: Props) {
  const [chunk, setChunk] = useState<ChunkDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const metric = refId ? metrics[refId] : undefined;

  useEffect(() => {
    setChunk(null);
    setError(null);
    if (refId && !metrics[refId]) api.chunk(refId).then(setChunk).catch((e) => setError(String(e)));
  }, [refId, metrics]);

  if (!refId) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4 backdrop-blur-sm" onClick={onClose}>
      <div className="fade-in max-h-[85vh] w-full max-w-3xl overflow-y-auto rounded-2xl border border-slate-200 bg-white shadow-pop"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-4 border-b border-slate-200 px-5 py-3">
          <div>
            <div className="section-title">{metric ? "Computed metric" : "Source passage"}</div>
            <div className="mt-0.5 break-all font-mono text-[11px] text-slate-400">{refId}</div>
          </div>
          <button onClick={onClose} className="rounded-md px-2 py-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700">✕</button>
        </div>
        <div className="p-5">
          {metric && (
            <div className="space-y-4">
              <div className="flex flex-wrap items-baseline gap-3">
                <div className="text-lg font-semibold text-slate-900">{metric.label}</div>
                <div className="text-sm text-slate-500">{metric.period}</div>
                <div className="ml-auto text-2xl font-semibold tabular-nums text-brand">{fmtMetric(metric.value, metric.unit)}</div>
              </div>
              <div>
                <div className="section-title mb-1">Formula</div>
                <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 font-mono text-xs text-slate-700">{metric.formula}</div>
              </div>
              {metric.note && <div className="rounded-lg bg-brand-light px-3 py-2 text-sm text-brand">{metric.note}</div>}
              <div>
                <div className="section-title mb-1">Inputs</div>
                <div className="overflow-hidden rounded-lg border border-slate-200">
                  <table className="w-full text-sm">
                    <thead className="table-head">
                      <tr><th className="px-3 py-2">Input</th><th className="px-3 py-2 text-right">Value (₹ mn)</th><th className="px-3 py-2">Source</th></tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {Object.entries(metric.inputs).map(([k, v]) => (
                        <tr key={k}>
                          <td className="px-3 py-2 text-slate-700">{k}</td>
                          <td className="px-3 py-2 text-right tabular-nums">{fmtNum(v.value)}</td>
                          <td className="px-3 py-2 text-slate-500">
                            {v.page && metric.doc_id ? (
                              <a className="text-brand hover:underline" target="_blank" rel="noreferrer"
                                href={`/api/documents/${metric.doc_id}/pdf#page=${v.page}`}>
                                p.{v.page}{v.raw_label ? ` · “${v.raw_label}”` : ""}
                              </a>
                            ) : (v.source ?? "—")}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
              <p className="text-xs text-slate-500">
                Computed in Python from the extracted restated statements. The language models never produce numbers.
              </p>
            </div>
          )}
          {chunk && (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <span className="chip border-slate-200 bg-slate-50 text-slate-600">{chunk.doc_type}</span>
                <span className="font-semibold text-slate-900">{chunk.section}</span>
                <span className="text-slate-500">
                  page {chunk.page}{chunk.page_end !== chunk.page ? `–${chunk.page_end}` : ""}
                </span>
                <div className="ml-auto flex gap-2">
                  {chunk.source_url?.startsWith("http") && (
                    <a href={chunk.source_url} target="_blank" rel="noreferrer" className="btn-secondary py-1.5 text-xs">SEBI filing</a>
                  )}
                  <a href={chunk.pdf_url} target="_blank" rel="noreferrer" className="btn-primary py-1.5 text-xs">
                    Open PDF at p.{chunk.page}
                  </a>
                </div>
              </div>
              <blockquote className="whitespace-pre-wrap rounded-lg border-l-4 border-brand bg-slate-50 p-4 text-sm leading-relaxed text-slate-700">
                {chunk.text}
              </blockquote>
            </div>
          )}
          {error && <div className="text-sm text-bear-dark">{error}</div>}
          {!metric && !chunk && !error && <div className="text-sm text-slate-500">Loading…</div>}
        </div>
      </div>
    </div>
  );
}
