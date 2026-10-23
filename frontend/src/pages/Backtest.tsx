import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { fmtDate, fmtNum, verdictColor } from "../format";
import type { BacktestRow } from "../types";

const pct = (v: number | null) =>
  v === null ? <span className="text-slate-600">—</span> :
  <span className={v >= 0 ? "text-bull" : "text-bear"}>{v >= 0 ? "+" : ""}{v.toFixed(1)}%</span>;

export default function Backtest() {
  const [rows, setRows] = useState<BacktestRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api.backtest().then(setRows).catch((e) => setError(String(e))); }, []);

  const judged = rows?.filter((r) => r.hit !== null) ?? [];
  const hits = judged.filter((r) => r.hit).length;
  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold">Back-test: verdict vs market</h1>
        <p className="mt-1 text-sm text-slate-400">
          For listed IPOs, the latest saved verdict is compared with the listing-day close and the latest
          close against the upper price band. Prices from Yahoo Finance (yfinance), with a CSV fallback for offline demos.
        </p>
      </div>
      {judged.length > 0 && (
        <div className="card inline-block">
          <div className="text-xs uppercase text-slate-500">Directional hit rate (listing day)</div>
          <div className="text-2xl font-bold">{hits}/{judged.length}</div>
          <div className="text-xs text-slate-500">Tiny sample: an illustration, not evidence of skill.</div>
        </div>
      )}
      {error && <div className="card text-bear">{error}</div>}
      {!rows && !error && <div className="text-slate-500">Loading prices…</div>}
      {rows && (
        <div className="overflow-x-auto rounded-xl border border-slate-800">
          <table className="w-full text-sm">
            <thead className="bg-slate-900 text-left text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-2">Company</th><th className="px-4 py-2">Listed</th>
                <th className="px-4 py-2 text-right">Issue ₹</th><th className="px-4 py-2 text-right">Listing close</th>
                <th className="px-4 py-2 text-right">Listing gain</th><th className="px-4 py-2 text-right">Latest</th>
                <th className="px-4 py-2 text-right">Return</th><th className="px-4 py-2">Verdict</th>
                <th className="px-4 py-2">Hit?</th><th className="px-4 py-2">Prices</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.ipo_id} className="border-t border-slate-800/70">
                  <td className="px-4 py-2"><Link className="hover:underline" to={`/ipo/${r.ipo_id}`}>{r.company}</Link></td>
                  <td className="px-4 py-2 text-slate-400">{fmtDate(r.listing_date)}</td>
                  <td className="px-4 py-2 text-right tabular-nums">{fmtNum(r.issue_price)}</td>
                  <td className="px-4 py-2 text-right tabular-nums">{fmtNum(r.listing_close)}</td>
                  <td className="px-4 py-2 text-right tabular-nums">{pct(r.listing_gain_pct)}</td>
                  <td className="px-4 py-2 text-right tabular-nums">{fmtNum(r.last_close)} <span className="text-xs text-slate-500">{r.last_date ? fmtDate(r.last_date) : ""}</span></td>
                  <td className="px-4 py-2 text-right tabular-nums">{pct(r.current_return_pct)}</td>
                  <td className={`px-4 py-2 ${verdictColor(r.verdict)}`}>{r.verdict ?? <span className="text-slate-600">no debate yet</span>}</td>
                  <td className="px-4 py-2">{r.hit === null ? "—" : r.hit ? "✅" : "❌"}</td>
                  <td className="px-4 py-2 text-xs text-slate-500">{r.price_source}</td>
                </tr>
              ))}
              {!rows.length && <tr><td colSpan={10} className="px-4 py-8 text-center text-slate-500">No listed IPOs yet.</td></tr>}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
