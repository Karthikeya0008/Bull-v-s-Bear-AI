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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" onClick={onClose}>
      <div className="card max-h-[85vh] w-full max-w-3xl overflow-y-auto" onClick={(e) => e.stopPropagation()}>
        <div className="mb-3 flex items-start justify-between gap-4">
          <div className="break-all font-mono text-xs text-slate-500">{refId}</div>
          <button onClick={onClose} className="text-slate-400 hover:text-white">✕</button>
        </div>
        {metric && (
          <div className="space-y-3">
            <div className="text-lg font-semibold">
              {metric.label} · {metric.period}:{" "}
              <span className="text-sky-300">{fmtMetric(metric.value, metric.unit)}</span>
            </div>
            <div className="rounded-md bg-slate-950 p-3 font-mono text-xs text-slate-300">{metric.formula}</div>
            {metric.note && <div className="text-sm text-slate-400">{metric.note}</div>}
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-slate-500">
                <tr><th className="py-1">Input</th><th>Value (₹ mn)</th><th>Source</th></tr>
              </thead>
              <tbody>
                {Object.entries(metric.inputs).map(([k, v]) => (
                  <tr key={k} className="border-t border-slate-800">
                    <td className="py-1 pr-2">{k}</td>
                    <td className="tabular-nums">{fmtNum(v.value)}</td>
                    <td className="text-slate-400">
                      {v.page && metric.doc_id ? (
                        <a className="text-sky-400 hover:underline" target="_blank" rel="noreferrer"
                           href={`/api/documents/${metric.doc_id}/pdf#page=${v.page}`}>
                          p.{v.page} {v.raw_label ? `· “${v.raw_label}”` : ""}
                        </a>
                      ) : (v.source ?? "—")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="text-xs text-slate-500">
              Computed in Python from the extracted restated statements; the LLM never produces numbers.
            </p>
          </div>
        )}
        {chunk && (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <span className="chip border-slate-700 text-slate-300">{chunk.doc_type}</span>
              <span className="font-medium">{chunk.section}</span>
              <span className="text-slate-400">
                page {chunk.page}{chunk.page_end !== chunk.page ? `–${chunk.page_end}` : ""}
              </span>
              <a href={chunk.pdf_url} target="_blank" rel="noreferrer"
                 className="ml-auto rounded-md bg-sky-600 px-3 py-1 text-xs font-medium hover:bg-sky-500">
                Open PDF at p.{chunk.page}
              </a>
              {chunk.source_url?.startsWith("http") && (
                <a href={chunk.source_url} target="_blank" rel="noreferrer" className="text-xs text-sky-400 hover:underline">
                  SEBI source
                </a>
              )}
            </div>
            <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-200">{chunk.text}</p>
          </div>
        )}
        {error && <div className="text-bear">{error}</div>}
        {!metric && !chunk && !error && <div className="text-slate-500">Loading…</div>}
      </div>
    </div>
  );
}
