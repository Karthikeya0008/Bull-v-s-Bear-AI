import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { fmtDate, fmtNum, statusBadge } from "../format";
import type { Ipo } from "../types";

const FILTERS = [
  { key: "all", label: "All" },
  { key: "upcoming", label: "Upcoming" },
  { key: "open", label: "Open" },
  { key: "listed", label: "Recently listed" },
];

export default function IpoList() {
  const [ipos, setIpos] = useState<Ipo[]>([]);
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [analysedOnly, setAnalysedOnly] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.ipos().then(setIpos).catch((e) => setError(String(e)));
  }, []);

  const shown = useMemo(
    () =>
      ipos.filter(
        (i) =>
          (filter === "all" || i.status === filter) &&
          (!analysedOnly || i.chunks > 0) &&
          i.company.toLowerCase().includes(query.toLowerCase()),
      ),
    [ipos, filter, query, analysedOnly],
  );
  const counts = useMemo(() => {
    const c: Record<string, number> = { all: ipos.length };
    ipos.forEach((i) => (c[i.status] = (c[i.status] ?? 0) + 1));
    return c;
  }, [ipos]);

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold">Indian IPO pipeline</h1>
        <p className="mt-1 text-sm text-slate-400">
          Every filing from SEBI and NSE goes through the same pipeline: parse and chunk the offer
          document, extract the restated financials, compute metrics, then let Bull and Bear agents
          debate with cited evidence.
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            onClick={() => setFilter(f.key)}
            className={`rounded-full border px-3 py-1 text-sm ${
              filter === f.key ? "border-slate-500 bg-slate-800" : "border-slate-800 text-slate-400 hover:text-white"
            }`}
          >
            {f.label} <span className="text-slate-500">{counts[f.key] ?? 0}</span>
          </button>
        ))}
        <label className="ml-2 flex items-center gap-2 text-sm text-slate-400">
          <input type="checkbox" checked={analysedOnly} onChange={(e) => setAnalysedOnly(e.target.checked)} />
          Analysed only
        </label>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search company…"
          className="ml-auto w-full rounded-md border border-slate-800 bg-slate-900 px-3 py-1.5 text-sm outline-none focus:border-slate-600 sm:w-64"
        />
      </div>
      {error && <div className="card text-bear">Could not reach the API: {error}</div>}
      <div className="overflow-x-auto rounded-xl border border-slate-800">
        <table className="w-full text-sm">
          <thead className="bg-slate-900 text-left text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-4 py-2">Company</th>
              <th className="px-4 py-2">Status</th>
              <th className="px-4 py-2">Price band (₹)</th>
              <th className="px-4 py-2">Issue dates</th>
              <th className="px-4 py-2">Listing</th>
              <th className="px-4 py-2 text-right">Fresh / OFS (₹ cr)</th>
              <th className="px-4 py-2 text-right">Analysis</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((i) => (
              <tr key={i.ipo_id} className="border-t border-slate-800/70 hover:bg-slate-900/60">
                <td className="px-4 py-2.5">
                  <Link to={`/ipo/${i.ipo_id}`} className="font-medium hover:underline">
                    {i.company}
                  </Link>
                  {i.sector && <div className="text-xs text-slate-500">{i.sector}</div>}
                </td>
                <td className="px-4 py-2.5">
                  <span className={`chip ${statusBadge[i.status]}`}>{i.status}</span>
                </td>
                <td className="px-4 py-2.5 tabular-nums">
                  {i.price_band_high ? `${fmtNum(i.price_band_low, 0)}–${fmtNum(i.price_band_high, 0)}` : "—"}
                </td>
                <td className="px-4 py-2.5 text-slate-400">
                  {i.issue_open ? `${fmtDate(i.issue_open)} → ${fmtDate(i.issue_close)}` : "—"}
                </td>
                <td className="px-4 py-2.5 text-slate-400">{fmtDate(i.listing_date)}</td>
                <td className="px-4 py-2.5 text-right tabular-nums text-slate-300">
                  {i.fresh_issue_cr !== null || i.ofs_cr !== null
                    ? `${fmtNum(i.fresh_issue_cr, 0)} / ${fmtNum(i.ofs_cr, 0)}`
                    : "—"}
                </td>
                <td className="px-4 py-2.5 text-right">
                  {i.chunks > 0 ? (
                    <span className="chip border-emerald-500/30 bg-emerald-500/10 text-emerald-300">
                      ready · {i.debates} debate{i.debates === 1 ? "" : "s"}
                    </span>
                  ) : (
                    <span className="text-xs text-slate-600">filing only</span>
                  )}
                </td>
              </tr>
            ))}
            {!shown.length && (
              <tr>
                <td colSpan={7} className="px-4 py-8 text-center text-slate-500">
                  No IPOs match.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
