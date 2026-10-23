import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, streamDebate, streamReplay } from "../api";
import CitationModal from "../components/CitationModal";
import DebateView, { emptyDebate, type DebateState } from "../components/DebateView";
import { fmtDate, fmtMetric, fmtNum, statusBadge, verdictColor } from "../format";
import type { Claim, DebateEvent, DebateSummary, Ipo, Metric, Verdict, Verification } from "../types";

const CARD_ORDER = ["revenue_growth", "revenue_cagr", "pat_growth", "ebitda_margin", "pat_margin", "roe",
  "debt_to_equity", "interest_coverage", "altman_z_em", "beneish_m", "pe_upper_band", "pe_vs_peers", "ofs_share"];

function reduce(state: DebateState, e: DebateEvent): DebateState {
  const s = { ...state };
  switch (e.type) {
    case "start":
      return { ...emptyDebate(), status: `Debate started · debaters: ${e.debater_model}`, models: { bull: String(e.debater_model), bear: String(e.debater_model) } };
    case "queries":
      s.queries = { ...s.queries, [e.side as string]: e.queries as string[] };
      s.status = `${e.side} agent planned ${(e.queries as string[]).length} retrieval queries`;
      return s;
    case "evidence":
      s.status = `${e.side} agent retrieved ${(e.chunk_ids as string[]).length} passages (BM25 + dense, RRF)`;
      return s;
    case "round":
      s.round = e.round as number;
      s.status = `Round ${e.round}: ${e.name}`;
      return s;
    case "claim":
      s.claims = [...s.claims, e.claim as Claim];
      return s;
    case "judging":
      s.status = `Judge verifying citations (fuzzy figures + NLI) · ${e.judge_model}`;
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
      s.status = e.replay ? "Replay finished (saved debate)" : `Done · debate ${e.debate_id}`;
      return s;
    case "error":
      s.error = String(e.message);
      return s;
    default:
      return s;
  }
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
  const cards = useMemo(() => CARD_ORDER.map((n) => metrics.find((m) => m.name === n)).filter(Boolean) as Metric[], [metrics]);
  const facts = metrics.filter((m) => m.name.startsWith("fact_") && m.period === metrics.find((x) => x.name === "debt_to_equity")?.period);

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

  if (!ipo) return <div className="text-slate-500">Loading…</div>;
  const latestDoc = ipo.documents?.[0];

  return (
    <div className="space-y-6">
      <Link to="/" className="text-sm text-slate-400 hover:text-white">← All IPOs</Link>
      <div className="flex flex-wrap items-start gap-4">
        <div>
          <h1 className="text-2xl font-semibold">{ipo.company}</h1>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-slate-400">
            <span className={`chip ${statusBadge[ipo.status]}`}>{ipo.status}</span>
            {ipo.sector && <span>{ipo.sector}</span>}
            {ipo.price_band_high && <span>· Band ₹{fmtNum(ipo.price_band_low, 0)}–{fmtNum(ipo.price_band_high, 0)}</span>}
            {ipo.issue_open && <span>· {fmtDate(ipo.issue_open)} → {fmtDate(ipo.issue_close)}</span>}
            {ipo.listing_date && <span>· Listing {fmtDate(ipo.listing_date)}</span>}
            {ipo.fresh_issue_cr !== null && <span>· Fresh ₹{fmtNum(ipo.fresh_issue_cr, 0)} cr / OFS ₹{fmtNum(ipo.ofs_cr, 0)} cr</span>}
          </div>
          <div className="mt-1 flex flex-wrap gap-2 text-xs text-slate-500">
            {ipo.documents?.map((d) => (
              <a key={d.doc_id} href={`/api/documents/${d.doc_id}/pdf`} target="_blank" rel="noreferrer" className="hover:text-sky-300">
                📄 {d.doc_type} filed {fmtDate(d.filed_date)} · {d.pages} pp · {d.chunks} chunks · {d.table_rows} table rows
                {d === latestDoc ? " (used for analysis)" : ""}
              </a>
            ))}
          </div>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <button disabled={running || !ipo.chunks} onClick={() => run("live")}
            className="rounded-lg bg-gradient-to-r from-emerald-600 to-red-600 px-5 py-2.5 font-semibold shadow-lg disabled:opacity-40">
            {running ? "Debating…" : "⚔ Start Debate"}
          </button>
          {running && <button onClick={() => abort.current?.abort()} className="rounded-lg border border-slate-700 px-3 py-2.5 text-sm">Stop</button>}
        </div>
      </div>

      {!ipo.chunks && (
        <div className="card text-sm text-slate-400">
          This IPO is in the registry but its offer document has not been ingested yet. Run
          <code className="mx-1 rounded bg-slate-950 px-1">python -m backend.ingest --ipo {ipo.ipo_id}</code>.
        </div>
      )}

      {facts.length > 0 && (
        <div className="flex flex-wrap gap-3 text-sm">
          {facts.map((m) => (
            <button key={m.metric_id} onClick={() => setCite(m.metric_id)} className="card py-2 text-left hover:border-slate-600">
              <div className="text-xs text-slate-500">{m.label} {m.period}</div>
              <div className="font-semibold tabular-nums">{fmtMetric(m.value, m.unit)}</div>
            </button>
          ))}
        </div>
      )}

      {cards.length > 0 && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4 lg:grid-cols-6">
          {cards.map((m) => (
            <button key={m.metric_id} onClick={() => setCite(m.metric_id)}
              className={`group card relative text-left hover:border-slate-600 ${m.status === "skipped" ? "opacity-60" : ""}`}>
              <div className="text-xs text-slate-500">{m.label}</div>
              <div className="mt-1 text-xl font-semibold tabular-nums">{m.status === "ok" ? fmtMetric(m.value, m.unit) : "n/a"}</div>
              <div className="text-[11px] text-slate-500">
                {m.period}{m.source_pages.length ? ` · p.${m.source_pages.slice(0, 3).join(",")}` : ""}
              </div>
              <div className="pointer-events-none absolute left-0 top-full z-20 mt-1 hidden w-72 rounded-md border border-slate-700 bg-slate-950 p-2 text-[11px] text-slate-300 shadow-xl group-hover:block">
                <div className="font-mono">{m.formula}</div>
                {m.note && <div className="mt-1 text-slate-400">{m.note}</div>}
              </div>
            </button>
          ))}
        </div>
      )}

      {debates.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="text-slate-500">Saved debates (replay works offline):</span>
          {debates.filter((d) => d.status === "done").slice(0, 6).map((d) => (
            <button key={d.debate_id} disabled={running} onClick={() => run("replay", d.debate_id)}
              className="chip border-slate-700 hover:bg-slate-800">
              ▶ {fmtDate(d.created_at)} · <span className={verdictColor(d.verdict)}>{d.verdict}</span>
              <span className="text-slate-500">({d.models?.bull})</span>
            </button>
          ))}
        </div>
      )}

      {debate.status !== "idle" && <DebateView state={debate} metrics={metricMap} onCite={setCite} />}
      <CitationModal refId={cite} metrics={metricMap} onClose={() => setCite(null)} />
    </div>
  );
}
