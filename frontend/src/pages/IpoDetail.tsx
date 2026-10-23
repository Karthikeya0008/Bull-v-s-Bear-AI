import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, streamDebate, streamReplay } from "../api";
import CitationModal from "../components/CitationModal";
import DebateView, { emptyDebate, type DebateState } from "../components/DebateView";
import { fmtDate, fmtMetric, fmtNum, statusBadge, verdictBadge } from "../format";
import type { Claim, DebateEvent, DebateSummary, Ipo, Metric, Verdict, Verification } from "../types";

const METRIC_GROUPS: { title: string; names: string[] }[] = [
  { title: "Growth", names: ["revenue_growth", "revenue_cagr", "pat_growth"] },
  { title: "Profitability", names: ["ebitda_margin", "pat_margin", "roe"] },
  { title: "Balance sheet & forensic", names: ["debt_to_equity", "interest_coverage", "altman_z_em", "beneish_m"] },
  { title: "Valuation & issue", names: ["pe_upper_band", "pe_vs_peers", "ofs_share"] },
];

function reduce(state: DebateState, e: DebateEvent): DebateState {
  const s = { ...state };
  switch (e.type) {
    case "start":
      return { ...emptyDebate(), status: `Debate started · debaters: ${e.debater_model}`, models: { bull: String(e.debater_model), bear: String(e.debater_model) } };
    case "queries":
      s.queries = { ...s.queries, [e.side as string]: e.queries as string[] };
      s.status = `${e.side === "bull" ? "Bull" : "Bear"} agent planned ${(e.queries as string[]).length} retrieval queries`;
      return s;
    case "evidence":
      s.status = `${e.side === "bull" ? "Bull" : "Bear"} agent retrieved ${(e.chunk_ids as string[]).length} passages (BM25 + dense, RRF)`;
      return s;
    case "round":
      s.round = e.round as number;
      s.status = `Round ${e.round}: ${e.name}`;
      return s;
    case "claim":
      s.claims = [...s.claims, e.claim as Claim];
      return s;
    case "judging":
      s.status = `Judge verifying citations (figures + NLI) · ${e.judge_model}`;
      return s;
    case "verification": {
      const v = e.result as Verification;
      s.verification = { ...s.verification, [v.claim_id]: v };
      return s;
    }
    case "verdict":
      s.verdict = e.verdict as Verdict;
      s.status = "Verdict ready";
      return s;
    case "done":
      s.done = true;
      s.models = { ...s.models, ...(e.models as Record<string, string>) };
      s.status = e.replay ? "Replay finished (saved debate)" : `Debate complete · ${e.debate_id}`;
      return s;
    case "error":
      s.error = String(e.message);
      return s;
    default:
      return s;
  }
}

function MetricCard({ m, onClick }: { m: Metric; onClick: () => void }) {
  const ok = m.status === "ok";
  return (
    <button onClick={onClick}
      className="group relative rounded-xl border border-slate-200 bg-white p-3.5 text-left shadow-card transition hover:border-brand/40 hover:shadow-pop">
      <div className="text-xs font-medium text-slate-500">{m.label}</div>
      <div className={`mt-1 text-xl font-semibold tabular-nums ${ok ? "text-slate-900" : "text-slate-400"}`}>
        {ok ? fmtMetric(m.value, m.unit) : "n/a"}
      </div>
      <div className="mt-0.5 text-[11px] text-slate-400">
        {m.period}{m.source_pages.length ? ` · p.${m.source_pages.slice(0, 3).join(", ")}` : ""}
      </div>
      <div className="pointer-events-none absolute left-0 top-full z-20 mt-2 hidden w-80 rounded-lg bg-slate-900 p-3 text-[11px] leading-relaxed text-slate-100 shadow-pop group-hover:block">
        <div className="mb-1 font-semibold text-white">Formula</div>
        <div className="font-mono text-slate-300">{m.formula}</div>
        {m.note && <div className="mt-2 text-slate-300">{m.note}</div>}
        <div className="mt-2 text-slate-400">Click for inputs and source pages</div>
      </div>
    </button>
  );
}

export default function IpoDetail() {
  const { ipoId = "" } = useParams();
  const [ipo, setIpo] = useState<Ipo | null>(null);
  const [metrics, setMetrics] = useState<Metric[]>([]);
  const [debates, setDebates] = useState<DebateSummary[]>([]);
  const [debate, setDebate] = useState<DebateState>(emptyDebate());
  const [cite, setCite] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const abort = useRef<AbortController | null>(null);

  const load = useCallback(() => {
    api.ipo(ipoId).then(setIpo);
    api.metrics(ipoId).then(setMetrics).catch(() => setMetrics([]));
    api.debates(ipoId).then(setDebates).catch(() => setDebates([]));
  }, [ipoId]);
  useEffect(() => { load(); return () => abort.current?.abort(); }, [load]);

  const metricMap = useMemo(() => Object.fromEntries(metrics.map((m) => [m.metric_id, m])), [metrics]);
  const byName = useMemo(() => Object.fromEntries(metrics.filter((m) => !m.name.startsWith("fact_")).map((m) => [m.name, m])), [metrics]);
  const latestPeriod = metrics.find((x) => x.name === "debt_to_equity")?.period;
  const facts = metrics.filter((m) => m.name.startsWith("fact_") && m.period === latestPeriod);

  const run = async (mode: "live" | "replay", debateId?: string) => {
    abort.current?.abort();
    abort.current = new AbortController();
    setRunning(true);
    setDebate({ ...emptyDebate(), status: mode === "live" ? "Starting debate…" : "Replaying saved debate…" });
    const onEvent = (e: DebateEvent) => setDebate((s) => reduce(s, e));
    try {
      if (mode === "live") await streamDebate(ipoId, onEvent, abort.current.signal);
      else await streamReplay(debateId!, onEvent, abort.current.signal);
    } catch (err) {
      if ((err as Error).name !== "AbortError") setDebate((s) => ({ ...s, error: String(err) }));
    } finally {
      setRunning(false);
      if (mode === "live") load();
    }
  };

  if (!ipo) return <div className="text-sm text-slate-500">Loading…</div>;
  const latestDoc = ipo.documents?.[0];
  const savedDebates = debates.filter((d) => d.status === "done").slice(0, 6);

  return (
    <div className="space-y-6">
      <Link to="/" className="inline-flex items-center gap-1 text-sm font-medium text-slate-500 hover:text-brand">← All IPOs</Link>

      {/* Header */}
      <div className="card p-5">
        <div className="flex flex-wrap items-start gap-4">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-2xl font-semibold tracking-tight text-slate-900">{ipo.company}</h1>
              <span className={`chip capitalize ${statusBadge[ipo.status]}`}>{ipo.status}</span>
            </div>
            {ipo.sector && <div className="mt-1 text-sm text-slate-500">{ipo.sector}{ipo.exchanges ? ` · ${ipo.exchanges.replace(",", " & ")}` : ""}</div>}
          </div>
          <div className="flex items-center gap-2">
            {running && <button onClick={() => abort.current?.abort()} className="btn-secondary">Stop</button>}
            <button disabled={running || !ipo.chunks} onClick={() => run("live")} className="btn-primary px-5 py-2.5">
              {running ? (
                <><span className="h-2 w-2 animate-pulse rounded-full bg-white" /> Debating…</>
              ) : (
                <>⚖ Start Debate</>
              )}
            </button>
          </div>
        </div>
        <dl className="mt-5 grid grid-cols-2 gap-4 border-t border-slate-100 pt-4 text-sm md:grid-cols-5">
          <div><dt className="section-title">Price band</dt><dd className="mt-1 font-medium tabular-nums">{ipo.price_band_high ? `₹${fmtNum(ipo.price_band_low, 0)} – ₹${fmtNum(ipo.price_band_high, 0)}` : "—"}</dd></div>
          <div><dt className="section-title">Issue window</dt><dd className="mt-1 font-medium">{ipo.issue_open ? `${fmtDate(ipo.issue_open)} → ${fmtDate(ipo.issue_close)}` : "—"}</dd></div>
          <div><dt className="section-title">Listing</dt><dd className="mt-1 font-medium">{fmtDate(ipo.listing_date)}</dd></div>
          <div><dt className="section-title">Fresh issue</dt><dd className="mt-1 font-medium tabular-nums">{ipo.fresh_issue_cr !== null ? `₹${fmtNum(ipo.fresh_issue_cr, 0)} cr` : "—"}</dd></div>
          <div><dt className="section-title">Offer for sale</dt><dd className="mt-1 font-medium tabular-nums">{ipo.ofs_cr !== null ? `₹${fmtNum(ipo.ofs_cr, 0)} cr` : "—"}</dd></div>
        </dl>
        {!!ipo.documents?.length && (
          <div className="mt-4 flex flex-wrap gap-2">
            {ipo.documents.map((d) => (
              <a key={d.doc_id} href={`/api/documents/${d.doc_id}/pdf`} target="_blank" rel="noreferrer"
                className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-xs transition hover:border-brand/40 ${
                  d === latestDoc ? "border-brand/30 bg-brand-light" : "border-slate-200 bg-white"}`}>
                <span className="text-base">📄</span>
                <span>
                  <span className="font-semibold text-slate-800">{d.doc_type}</span>
                  <span className="text-slate-500"> · filed {fmtDate(d.filed_date)}</span>
                  <span className="block text-slate-500">{d.pages} pages · {d.chunks} chunks · {d.table_rows} table rows</span>
                </span>
                {d === latestDoc && <span className="chip border-brand/30 bg-white text-brand">Used for analysis</span>}
              </a>
            ))}
          </div>
        )}
      </div>

      {!ipo.chunks && (
        <div className="card text-sm text-slate-600">
          This IPO is in the registry but its offer document has not been ingested yet. Run
          <code className="mx-1 rounded bg-slate-100 px-1.5 py-0.5 text-slate-800">python -m backend.ingest --ipo {ipo.ipo_id}</code>.
        </div>
      )}

      {/* Key figures */}
      {facts.length > 0 && (
        <section>
          <div className="mb-2 flex items-baseline gap-2">
            <h2 className="text-sm font-semibold text-slate-900">Key figures</h2>
            <span className="text-xs text-slate-500">{latestPeriod} · restated consolidated</span>
          </div>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
            {facts.map((m) => (
              <button key={m.metric_id} onClick={() => setCite(m.metric_id)}
                className="rounded-xl border border-slate-200 bg-white p-3.5 text-left shadow-card transition hover:border-brand/40">
                <div className="text-xs font-medium text-slate-500">{m.label}</div>
                <div className="mt-1 text-lg font-semibold tabular-nums text-slate-900">{fmtMetric(m.value, m.unit)}</div>
              </button>
            ))}
          </div>
        </section>
      )}

      {/* Metrics */}
      {metrics.length > 0 && (
        <section className="space-y-4">
          <div className="flex items-baseline gap-2">
            <h2 className="text-sm font-semibold text-slate-900">Computed metrics</h2>
            <span className="text-xs text-slate-500">Hover for the formula · click for inputs and source pages</span>
          </div>
          {METRIC_GROUPS.map((g) => {
            const ms = g.names.map((n) => byName[n]).filter(Boolean);
            if (!ms.length) return null;
            return (
              <div key={g.title}>
                <div className="section-title mb-2">{g.title}</div>
                <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                  {ms.map((m) => <MetricCard key={m.metric_id} m={m} onClick={() => setCite(m.metric_id)} />)}
                </div>
              </div>
            );
          })}
        </section>
      )}

      {/* Saved debates */}
      {savedDebates.length > 0 && (
        <section className="card">
          <div className="mb-3 flex items-baseline gap-2">
            <h2 className="text-sm font-semibold text-slate-900">Saved debates</h2>
            <span className="text-xs text-slate-500">Replay works offline, with no LLM calls</span>
          </div>
          <div className="flex flex-wrap gap-2">
            {savedDebates.map((d) => (
              <button key={d.debate_id} disabled={running} onClick={() => run("replay", d.debate_id)}
                className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-left text-xs transition hover:border-brand/40 hover:bg-slate-50 disabled:opacity-50">
                <span className="flex h-6 w-6 items-center justify-center rounded-full bg-brand-light text-brand">▶</span>
                <span>
                  <span className={`chip ${verdictBadge(d.verdict)}`}>{d.verdict}</span>
                  <span className="mt-0.5 block text-slate-500">{fmtDate(d.created_at)} · {d.models?.bull}</span>
                </span>
              </button>
            ))}
          </div>
        </section>
      )}

      {debate.status !== "idle" && (
        <section className="space-y-3">
          <h2 className="text-sm font-semibold text-slate-900">Debate</h2>
          <DebateView state={debate} metrics={metricMap} onCite={setCite} />
        </section>
      )}
      <CitationModal refId={cite} metrics={metricMap} onClose={() => setCite(null)} />
    </div>
  );
}
