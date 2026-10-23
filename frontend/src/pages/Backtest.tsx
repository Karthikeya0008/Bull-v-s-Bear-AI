import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { fmtDate, fmtNum, verdictBadge } from "../format";
import type { BacktestRow } from "../types";

const pct = (v: number | null) =>
  v === null ? <span className="text-slate-400">—</span> :
  <span className={`font-medium ${v >= 0 ? "text-bull-dark" : "text-bear-dark"}`}>{v >= 0 ? "+" : ""}{v.toFixed(1)}%</span>;

export default function Backtest() {
  const [rows, setRows] = useState<BacktestRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api.backtest().then(setRows).catch((e) => setError(String(e))); }, []);

  const judged = rows?.filter((r) => r.hit !== null) ?? [];
  const hits = judged.filter((r) => r.hit).length;
  const avg = (k: "listing_gain_pct" | "current_return_pct") => {
    const v = (rows ?? []).map((r) => r[k]).filter((x): x is number => x !== null);
    return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Back-test: verdict vs market</h1>
        <p className="mt-1 max-w-3xl text-sm text-slate-600">
          For listed IPOs with a saved debate, the latest verdict is compared with the listing-day close and the
          latest close against the upper price band. Prices from Yahoo Finance, with a CSV fallback for offline demos.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <div className="card">
          <div className="section-title">IPOs evaluated</div>
          <div className="mt-1.5 text-2xl font-semibold">{rows?.length ?? "—"}</div>
        </div>
        <div className="card">
          <div className="section-title">Directional hit rate</div>
          <div className="mt-1.5 text-2xl font-semibold">{judged.length ? `${hits}/${judged.length}` : "—"}</div>
          <div className="mt-0.5 text-xs text-slate-500">Neutral verdicts excluded</div>
        </div>
        <div className="card">
          <div className="section-title">Avg listing gain</div>
          <div className="mt-1.5 text-2xl">{pct(avg("listing_gain_pct"))}</div>
        </div>
        <div className="card">
          <div className="section-title">Avg return to date</div>
          <div className="mt-1.5 text-2xl">{pct(avg("current_return_pct"))}</div>
        </div>
      </div>

      {error && <div className="card text-sm text-bear-dark">{error}</div>}
      {!rows && !error && <div className="text-sm text-slate-500">Loading prices…</div>}
      {rows && (
        <div className="card overflow-x-auto p-0">
          <table className="w-full text-sm">
            <thead className="table-head">
              <tr>
                <th className="px-4 py-2.5">Company</th><th className="px-4 py-2.5">Listed</th>
                <th className="px-4 py-2.5 text-right">Issue ₹</th><th className="px-4 py-2.5 text-right">Listing close</th>
                <th className="px-4 py-2.5 text-right">Listing gain</th><th className="px-4 py-2.5 text-right">Latest close</th>
                <th className="px-4 py-2.5 text-right">Return</th><th className="px-4 py-2.5">Verdict</th>
                <th className="px-4 py-2.5 text-center">Hit</th><th className="px-4 py-2.5">Prices</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rows.map((r) => (
                <tr key={r.ipo_id} className="hover:bg-slate-50">
                  <td className="px-4 py-3">
                    <Link className="font-medium text-slate-900 hover:text-brand" to={`/ipo/${r.ipo_id}`}>{r.company}</Link>
                    {r.symbol && <div className="text-xs text-slate-500">NSE: {r.symbol}</div>}
                  </td>
                  <td className="px-4 py-3 text-slate-600">{fmtDate(r.listing_date)}</td>
                  <td className="px-4 py-3 text-right tabular-nums">{fmtNum(r.issue_price)}</td>
                  <td className="px-4 py-3 text-right tabular-nums">{fmtNum(r.listing_close)}</td>
                  <td className="px-4 py-3 text-right tabular-nums">{pct(r.listing_gain_pct)}</td>
                  <td className="px-4 py-3 text-right tabular-nums">
                    {fmtNum(r.last_close)}
                    <div className="text-xs text-slate-400">{r.last_date ? fmtDate(r.last_date) : ""}</div>
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums">{pct(r.current_return_pct)}</td>
                  <td className="px-4 py-3">
                    {r.verdict ? <span className={`chip ${verdictBadge(r.verdict)}`}>{r.verdict}</span>
                      : <span className="text-xs text-slate-400">No debate yet</span>}
                  </td>
                  <td className="px-4 py-3 text-center">
                    {r.hit === null ? <span className="text-slate-400">—</span> :
                      <span className={`chip ${r.hit ? "border-bull-line bg-bull-soft text-bull-dark" : "border-bear-line bg-bear-soft text-bear-dark"}`}>
                        {r.hit ? "Hit" : "Miss"}
                      </span>}
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-500">{r.price_source}</td>
                </tr>
              ))}
              {!rows.length && <tr><td colSpan={10} className="px-4 py-10 text-center text-slate-500">No listed IPOs with a saved debate yet.</td></tr>}
            </tbody>
          </table>
        </div>
      )}
      <p className="text-xs text-slate-500">Small sample: this illustrates the method and is not evidence of predictive skill.</p>
    </div>
  );
}
