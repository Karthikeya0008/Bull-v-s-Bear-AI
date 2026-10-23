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
  supported: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
  partially_supported: "border-amber-500/40 bg-amber-500/10 text-amber-300",
  struck: "border-red-500/40 bg-red-500/10 text-red-300",
};

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
    <div className={`fade-in rounded-lg border border-slate-800 border-l-4 ${side} bg-slate-900/80 p-3 ${decisive ? "ring-1 ring-sky-500/60" : ""}`}>
      <div className="mb-1 flex items-center gap-2 text-[11px] text-slate-500">
        <span className="font-mono">{claim.claim_id}</span>
        <span>{"●".repeat(claim.strength)}{"○".repeat(5 - claim.strength)}</span>
        {claim.rebuts && <span className="text-slate-400">↩ rebuts {claim.rebuts}</span>}
        {decisive && <span className="text-sky-300">★ decisive</span>}
        {v && <span className={`chip ml-auto ${STATUS_STYLE[v.status]}`}>{v.status.replace("_", " ")}</span>}
      </div>
      <p className={`text-sm leading-relaxed ${struck ? "text-slate-500 line-through decoration-red-400/70" : "text-slate-100"}`}>
        {claim.text}
      </p>
      <div className="mt-2 flex flex-wrap gap-1">
        {claim.evidence.map((ref) => {
          const bad = v?.invalid_refs.includes(ref);
          return (
            <button key={ref} onClick={() => !bad && onCite(ref)} title={ref}
              className={`chip ${bad ? "cursor-not-allowed border-red-500/40 text-red-400 line-through" :
                metrics[ref] ? "border-sky-500/40 text-sky-300 hover:bg-sky-500/10" :
                "border-slate-600 text-slate-300 hover:bg-slate-800"}`}>
              {metrics[ref] ? "ƒ" : "📄"} {refLabel(ref, metrics)}
            </button>
          );
        })}
        {!claim.evidence.length && <span className="chip border-red-500/40 text-red-400">no citation</span>}
      </div>
      {v && v.status !== "supported" && (
        <div className={`mt-2 text-xs ${struck ? "text-red-300" : "text-amber-300"}`}>Judge: {v.reason}</div>
      )}
    </div>
  );
}

export function VerdictPanel({ verdict, claims, onCite, metrics }: {
  verdict: Verdict; claims: Claim[]; onCite: (r: string) => void; metrics: Record<string, Metric>;
}) {
  const byId = Object.fromEntries(claims.map((c) => [c.claim_id, c]));
  const list = (ids: string[], side: Side) => (
    <ul className="space-y-1.5">
      {ids.map((id) => byId[id] && (
        <li key={id} className="text-sm">
          <span className={`font-mono text-xs ${side === "bull" ? "text-bull" : "text-bear"}`}>{id}</span>{" "}
          <span className="text-slate-300">{byId[id].text}</span>{" "}
          {byId[id].evidence.slice(0, 2).map((r) => (
            <button key={r} onClick={() => onCite(r)} className="chip ml-1 border-slate-700 text-slate-400 hover:text-white">
              {refLabel(r, metrics)}
            </button>
          ))}
        </li>
      ))}
      {!ids.length && <li className="text-sm text-slate-500">None survived verification.</li>}
    </ul>
  );
  return (
    <div className="card fade-in border-sky-500/30">
      <div className="flex flex-wrap items-end gap-6">
        <div>
          <div className="text-xs uppercase tracking-wide text-slate-500">Judge verdict</div>
          <div className={`text-3xl font-bold ${verdictColor(verdict.verdict)}`}>{verdict.verdict}</div>
        </div>
        <div>
          <div className="text-xs uppercase tracking-wide text-slate-500">Confidence</div>
          <div className="text-xl font-semibold">{verdict.confidence} <span className="text-sm text-slate-400">({verdict.confidence_score}/100)</span></div>
        </div>
        <div className="text-sm text-slate-400">
          {verdict.struck} of {verdict.total_claims} claims struck · judged by <span className="font-mono text-slate-300">{verdict.model}</span>
        </div>
        {verdict.scores && (
          <div className="ml-auto w-full max-w-xs">
            <div className="flex justify-between text-xs text-slate-500"><span>Bull {verdict.scores.bull.toFixed(1)}</span><span>Bear {verdict.scores.bear.toFixed(1)}</span></div>
            <div className="mt-1 flex h-2 overflow-hidden rounded-full bg-slate-800">
              <div className="bg-bull" style={{ width: `${(100 * verdict.scores.bull) / Math.max(0.01, verdict.scores.bull + verdict.scores.bear)}%` }} />
              <div className="flex-1 bg-bear" />
            </div>
          </div>
        )}
      </div>
      {verdict.rationale && <p className="mt-3 text-sm text-slate-300">{verdict.rationale}</p>}
      <div className="mt-4 grid gap-4 md:grid-cols-2">
        <div><div className="mb-2 text-sm font-semibold text-bull">Most decisive bull claims</div>{list(verdict.decisive_bull, "bull")}</div>
        <div><div className="mb-2 text-sm font-semibold text-bear">Most decisive bear claims</div>{list(verdict.decisive_bear, "bear")}</div>
      </div>
      <p className="mt-4 rounded-md bg-slate-950 p-2 text-xs text-slate-500">⚠ {verdict.disclaimer}</p>
    </div>
  );
}

export default function DebateView({ state, metrics, onCite }: {
  state: DebateState; metrics: Record<string, Metric>; onCite: (r: string) => void;
}) {
  const decisive = new Set([...(state.verdict?.decisive_bull ?? []), ...(state.verdict?.decisive_bear ?? [])]);
  const column = (side: Side) => (
    <div className="space-y-4">
      <div className={`flex items-center gap-2 text-lg font-semibold ${side === "bull" ? "text-bull" : "text-bear"}`}>
        {side === "bull" ? "▲ Bull" : "▼ Bear"}
        <span className="font-mono text-xs font-normal text-slate-500">{state.models[side] ?? ""}</span>
      </div>
      {state.queries[side].length > 0 && (
        <div className="flex flex-wrap gap-1">
          {state.queries[side].map((q) => <span key={q} className="chip border-slate-800 text-slate-400">🔎 {q}</span>)}
        </div>
      )}
      {[1, 2, 3].map((r) => {
        const claims = state.claims.filter((c) => c.stance === side && c.round === r);
        if (!claims.length) return null;
        return (
          <div key={r} className="space-y-2">
            <div className="text-xs uppercase tracking-wide text-slate-500">Round {r} · {ROUND_LABEL[r]}</div>
            {claims.map((c) => (
              <ClaimCard key={c.claim_id} claim={c} v={state.verification[c.claim_id]} metrics={metrics}
                onCite={onCite} decisive={decisive.has(c.claim_id)} />
            ))}
          </div>
        );
      })}
    </div>
  );
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-2 text-sm text-slate-400">
        {!state.done && !state.error && state.status !== "idle" && <span className="h-2 w-2 animate-pulse rounded-full bg-sky-400" />}
        <span>{state.error ? <span className="text-bear">Error: {state.error}</span> : state.status}</span>
      </div>
      {state.verdict && <VerdictPanel verdict={state.verdict} claims={state.claims} onCite={onCite} metrics={metrics} />}
      <div className="grid gap-6 md:grid-cols-2">
        {column("bull")}
        {column("bear")}
      </div>
    </div>
  );
}
