import type { Claim, Metric, Side, Verdict, Verification } from "../types";
import { verdictColor } from "../format";

export interface DebateState {
  status: string;
  log: string[];
  queries: Record<Side, string[]>;
  claims: Claim[];
  verification: Record<string, Verification>;
  verdict: Verdict | null;
  models: Record<string, string>;
  round: number;
  done: boolean;
  error: string | null;
}

export const emptyDebate = (): DebateState => ({
  status: "idle", log: [], queries: { bull: [], bear: [] }, claims: [], verification: {},
  verdict: null, models: {}, round: 0, done: false, error: null,
});

const ROUND_LABEL: Record<number, string> = { 1: "Opening", 2: "Rebuttal", 3: "Closing" };
const STATUS_STYLE: Record<string, string> = {
  supported: "border-emerald-200 bg-emerald-50 text-emerald-700",
  partially_supported: "border-amber-200 bg-amber-50 text-amber-700",
  struck: "border-rose-200 bg-rose-50 text-rose-700",
};
const STATUS_LABEL: Record<string, string> = {
  supported: "✓ Supported", partially_supported: "◐ Partial", struck: "✕ Struck",
};

/** Hide raw evidence ids the model sometimes pastes into prose; they are shown as chips. */
const cleanText = (t: string) => t.replace(/\s*\[[^\]]*[:/][^\]]*\]/g, "").replace(/\s+([.,;])/g, "$1");

function refLabel(ref: string, metrics: Record<string, Metric>): string {
  const m = metrics[ref];
  if (m) return `${m.label} ${m.period}`;
  const page = ref.match(/\/p0*(\d+)\//);
  const doc = ref.split("/")[1];
  return page ? `${doc} p.${page[1]}` : ref;
}

function ClaimCard({ claim, v, metrics, onCite, decisive }: {
  claim: Claim; v?: Verification; metrics: Record<string, Metric>;
  onCite: (ref: string) => void; decisive: boolean;
}) {
  const struck = v?.status === "struck";
  const side = claim.stance === "bull" ? "border-l-bull" : "border-l-bear";
  return (
    <div className={`fade-in rounded-lg border border-slate-200 border-l-4 ${side} bg-white p-3.5 shadow-card ${
      decisive ? "ring-2 ring-brand/25" : ""} ${struck ? "bg-slate-50" : ""}`}>
      <div className="mb-1.5 flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
        <span className="font-mono font-medium text-slate-600">{claim.claim_id}</span>
        <span title={`Strength ${claim.strength}/5`} className="tracking-tight text-slate-400">
          {"●".repeat(claim.strength)}<span className="text-slate-200">{"●".repeat(5 - claim.strength)}</span>
        </span>
        {claim.rebuts && <span className="rounded bg-slate-100 px-1.5 py-0.5 text-slate-600">↩ rebuts {claim.rebuts}</span>}
        {decisive && <span className="rounded bg-brand-light px-1.5 py-0.5 font-medium text-brand">★ Decisive</span>}
        {v && <span className={`chip ml-auto ${STATUS_STYLE[v.status]}`}>{STATUS_LABEL[v.status]}</span>}
      </div>
      <p className={`text-sm leading-relaxed ${struck ? "text-slate-400 line-through decoration-rose-400" : "text-slate-800"}`}>
        {cleanText(claim.text)}
      </p>
      <div className="mt-2.5 flex flex-wrap gap-1.5">
        {claim.evidence.map((ref) => {
          const bad = v?.invalid_refs.includes(ref);
          return (
            <button key={ref} onClick={() => !bad && onCite(ref)} title={ref}
              className={`chip ${bad ? "cursor-not-allowed border-rose-200 bg-rose-50 text-rose-500 line-through" :
                metrics[ref] ? "border-indigo-200 bg-indigo-50 text-indigo-700 hover:bg-indigo-100" :
                "border-slate-200 bg-slate-50 text-slate-700 hover:border-slate-300 hover:bg-white"}`}>
              {metrics[ref] ? "ƒx" : "📄"} {refLabel(ref, metrics)}
            </button>
          );
        })}
        {!claim.evidence.length && <span className="chip border-rose-200 bg-rose-50 text-rose-600">No citation</span>}
      </div>
      {v && v.status !== "supported" && (
        <div className={`mt-2.5 rounded-md px-2.5 py-1.5 text-xs ${struck ? "bg-rose-50 text-rose-700" : "bg-amber-50 text-amber-800"}`}>
          <span className="font-semibold">Judge:</span> {v.reason}
        </div>
      )}
    </div>
  );
}

export function VerdictPanel({ verdict, claims, onCite, metrics }: {
  verdict: Verdict; claims: Claim[]; onCite: (r: string) => void; metrics: Record<string, Metric>;
}) {
  const byId = Object.fromEntries(claims.map((c) => [c.claim_id, c]));
  const bullShare = verdict.scores
    ? (100 * verdict.scores.bull) / Math.max(0.01, verdict.scores.bull + verdict.scores.bear) : 50;
  const list = (ids: string[], side: Side) => (
    <ul className="space-y-2">
      {ids.map((id) => byId[id] && (
        <li key={id} className="rounded-lg border border-slate-200 bg-white p-2.5 text-sm">
          <span className={`font-mono text-xs font-semibold ${side === "bull" ? "text-bull-dark" : "text-bear-dark"}`}>{id}</span>{" "}
          <span className="text-slate-700">{cleanText(byId[id].text)}</span>
          <div className="mt-1.5 flex flex-wrap gap-1">
            {byId[id].evidence.slice(0, 3).map((r) => (
              <button key={r} onClick={() => onCite(r)} className="chip border-slate-200 bg-slate-50 text-slate-600 hover:bg-white">
                {refLabel(r, metrics)}
              </button>
            ))}
          </div>
        </li>
      ))}
      {!ids.length && <li className="text-sm text-slate-500">None survived verification.</li>}
    </ul>
  );
  return (
    <div className="fade-in overflow-hidden rounded-xl border border-slate-200 bg-white shadow-card">
      <div className="flex h-1.5">
        <div className="bg-bull" style={{ width: `${bullShare}%` }} />
        <div className="flex-1 bg-bear" />
      </div>
      <div className="p-5">
        <div className="flex flex-wrap items-end gap-x-10 gap-y-4">
          <div>
            <div className="section-title">Judge verdict</div>
            <div className={`mt-1 text-3xl font-bold tracking-tight ${verdictColor(verdict.verdict)}`}>{verdict.verdict}</div>
          </div>
          <div>
            <div className="section-title">Confidence</div>
            <div className="mt-1 text-xl font-semibold text-slate-900">
              {verdict.confidence} <span className="text-sm font-normal text-slate-500">· {verdict.confidence_score}/100</span>
            </div>
          </div>
          <div>
            <div className="section-title">Claims struck</div>
            <div className="mt-1 text-xl font-semibold text-slate-900">
              {verdict.struck} <span className="text-sm font-normal text-slate-500">of {verdict.total_claims}</span>
            </div>
          </div>
          {verdict.scores && (
            <div className="min-w-[200px] flex-1">
              <div className="flex justify-between text-xs font-medium">
                <span className="text-bull-dark">Bull {verdict.scores.bull.toFixed(1)}</span>
                <span className="text-bear-dark">Bear {verdict.scores.bear.toFixed(1)}</span>
              </div>
              <div className="mt-1.5 flex h-2 overflow-hidden rounded-full bg-slate-100">
                <div className="bg-bull" style={{ width: `${bullShare}%` }} />
                <div className="flex-1 bg-bear" />
              </div>
              <div className="mt-1 text-[11px] text-slate-500">Rule-based baseline (strength × verification)</div>
            </div>
          )}
        </div>
        <div className="mt-3 text-xs text-slate-500">
          Judged by <span className="font-mono text-slate-700">{verdict.model}</span>
        </div>
        {verdict.rationale && <p className="mt-3 text-sm leading-relaxed text-slate-700">{verdict.rationale}</p>}
        <div className="mt-5 grid gap-4 md:grid-cols-2">
          <div className="rounded-lg bg-bull-soft p-3">
            <div className="mb-2 text-sm font-semibold text-bull-dark">▲ Most decisive bull claims</div>
            {list(verdict.decisive_bull, "bull")}
          </div>
          <div className="rounded-lg bg-bear-soft p-3">
            <div className="mb-2 text-sm font-semibold text-bear-dark">▼ Most decisive bear claims</div>
            {list(verdict.decisive_bear, "bear")}
          </div>
        </div>
        <p className="mt-4 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          ⚠ {verdict.disclaimer}
        </p>
      </div>
    </div>
  );
}

export default function DebateView({ state, metrics, onCite }: {
  state: DebateState; metrics: Record<string, Metric>; onCite: (r: string) => void;
}) {
  const decisive = new Set([...(state.verdict?.decisive_bull ?? []), ...(state.verdict?.decisive_bear ?? [])]);
  const column = (side: Side) => {
    const isBull = side === "bull";
    const claims = state.claims.filter((c) => c.stance === side);
    return (
      <div className="space-y-4">
        <div className={`flex items-center gap-3 rounded-xl border px-4 py-3 ${
          isBull ? "border-bull-line bg-bull-soft" : "border-bear-line bg-bear-soft"}`}>
          <span className={`flex h-8 w-8 items-center justify-center rounded-lg text-white ${isBull ? "bg-bull" : "bg-bear"}`}>
            {isBull ? "▲" : "▼"}
          </span>
          <div>
            <div className={`font-semibold ${isBull ? "text-bull-dark" : "text-bear-dark"}`}>{isBull ? "Bull case" : "Bear case"}</div>
            <div className="font-mono text-[11px] text-slate-500">{state.models[side] ?? "—"}</div>
          </div>
          <span className="ml-auto text-xs text-slate-500">{claims.length} claims</span>
        </div>
        {state.queries[side].length > 0 && (
          <div>
            <div className="section-title mb-1.5">Retrieval queries</div>
            <div className="flex flex-wrap gap-1.5">
              {state.queries[side].map((q) => (
                <span key={q} className="chip border-slate-200 bg-white text-slate-600">🔎 {q}</span>
              ))}
            </div>
          </div>
        )}
        {[1, 2, 3].map((r) => {
          const rc = claims.filter((c) => c.round === r);
          if (!rc.length) return null;
          return (
            <div key={r} className="space-y-2.5">
              <div className="flex items-center gap-2">
                <span className="section-title">Round {r} · {ROUND_LABEL[r]}</span>
                <span className="h-px flex-1 bg-slate-200" />
              </div>
              {rc.map((c) => (
                <ClaimCard key={c.claim_id} claim={c} v={state.verification[c.claim_id]} metrics={metrics}
                  onCite={onCite} decisive={decisive.has(c.claim_id)} />
              ))}
            </div>
          );
        })}
      </div>
    );
  };
  return (
    <div className="space-y-6">
      <div className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-sm ${
        state.error ? "border-rose-200 bg-rose-50 text-rose-700" : "border-slate-200 bg-white text-slate-600"}`}>
        {!state.done && !state.error && state.status !== "idle" && (
          <span className="h-2 w-2 animate-pulse rounded-full bg-brand" />
        )}
        {state.done && !state.error && <span className="text-emerald-600">✓</span>}
        <span>{state.error ? `Error: ${state.error}` : state.status}</span>
        {state.round > 0 && !state.done && (
          <span className="ml-auto flex gap-1">
            {[1, 2, 3].map((r) => (
              <span key={r} className={`h-1.5 w-8 rounded-full ${r <= state.round ? "bg-brand" : "bg-slate-200"}`} />
            ))}
          </span>
        )}
      </div>
      {state.verdict && <VerdictPanel verdict={state.verdict} claims={state.claims} onCite={onCite} metrics={metrics} />}
      <div className="grid gap-6 lg:grid-cols-2">
        {column("bull")}
        {column("bear")}
      </div>
    </div>
  );
}
