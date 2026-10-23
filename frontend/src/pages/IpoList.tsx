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

function Stat({ label, value, hint }: { label: string; value: number | string; hint?: string }) {
  return (
    <div className="card">
      <div className="section-title">{label}</div>
      <div className="mt-1.5 text-2xl font-semibold tabular-nums text-slate-900">{value}</div>
      {hint && <div className="mt-0.5 text-xs text-slate-500">{hint}</div>}
    </div>
  );
}

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
  const analysed = ipos.filter((i) => i.chunks > 0).length;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Indian IPO pipeline</h1>
          <p className="mt-1 max-w-3xl text-sm text-slate-600">
            Every filing from SEBI and NSE runs through the same pipeline: parse the offer document, extract
            restated financials, compute metrics, then let Bull and Bear agents debate with cited evidence.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <Stat label="Tracked IPOs" value={counts.all ?? 0} hint="SEBI + NSE watcher" />
        <Stat label="Upcoming" value={counts.upcoming ?? 0} />
        <Stat label="Open now" value={counts.open ?? 0} />
        <Stat label="Recently listed" value={counts.listed ?? 0} />
        <Stat label="Fully analysed" value={analysed} hint="Offer document ingested" />
      </div>

      <div className="card p-0">
        <div className="flex flex-wrap items-center gap-3 border-b border-slate-200 px-4 py-3">
          <div className="inline-flex rounded-lg border border-slate-200 bg-slate-50 p-0.5">
            {FILTERS.map((f) => (
              <button
                key={f.key}
                onClick={() => setFilter(f.key)}
                className={`rounded-md px-3 py-1.5 text-sm font-medium transition ${
                  filter === f.key ? "bg-white text-slate-900 shadow-card" : "text-slate-500 hover:text-slate-800"
                }`}
              >
                {f.label} <span className="ml-0.5 text-xs text-slate-400">{counts[f.key] ?? 0}</span>
              </button>
            ))}
          </div>
          <label className="flex items-center gap-2 text-sm text-slate-600">
            <input type="checkbox" className="accent-brand" checked={analysedOnly}
              onChange={(e) => setAnalysedOnly(e.target.checked)} />
            Analysed only
          </label>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search company…"
            className="ml-auto w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm outline-none transition placeholder:text-slate-400 focus:border-brand focus:ring-2 focus:ring-brand/15 sm:w-64"
          />
        </div>
        {error && <div className="px-4 py-3 text-sm text-bear-dark">Could not reach the API: {error}</div>}
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="table-head">
              <tr>
                <th className="px-4 py-2.5">Company</th>
                <th className="px-4 py-2.5">Status</th>
                <th className="px-4 py-2.5">Price band (₹)</th>
                <th className="px-4 py-2.5">Issue dates</th>
                <th className="px-4 py-2.5">Listing</th>
                <th className="px-4 py-2.5 text-right">Fresh / OFS (₹ cr)</th>
                <th className="px-4 py-2.5 text-right">Analysis</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {shown.map((i) => (
                <tr key={i.ipo_id} className="transition hover:bg-slate-50">
                  <td className="px-4 py-3">
                    <Link to={`/ipo/${i.ipo_id}`} className="font-medium text-slate-900 hover:text-brand">
                      {i.company}
                    </Link>
                    {i.sector && <div className="text-xs text-slate-500">{i.sector}</div>}
                  </td>
                  <td className="px-4 py-3">
                    <span className={`chip capitalize ${statusBadge[i.status]}`}>{i.status}</span>
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 tabular-nums text-slate-700">
                    {i.price_band_high ? `${fmtNum(i.price_band_low, 0)} – ${fmtNum(i.price_band_high, 0)}` : "—"}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-slate-600">
                    {i.issue_open ? `${fmtDate(i.issue_open)} → ${fmtDate(i.issue_close)}` : "—"}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-slate-600">{fmtDate(i.listing_date)}</td>
                  <td className="whitespace-nowrap px-4 py-3 text-right tabular-nums text-slate-700">
                    {i.fresh_issue_cr !== null || i.ofs_cr !== null
                      ? `${fmtNum(i.fresh_issue_cr, 0)} / ${fmtNum(i.ofs_cr, 0)}`
                      : "—"}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-right">
                    {i.chunks > 0 ? (
                      <Link to={`/ipo/${i.ipo_id}`}
                        className="chip border-brand/20 bg-brand-light text-brand hover:bg-brand hover:text-white">
                        Ready · {i.debates} debate{i.debates === 1 ? "" : "s"} →
                      </Link>
                    ) : (
                      <span className="text-xs text-slate-400">Filing only</span>
                    )}
                  </td>
                </tr>
              ))}
              {!shown.length && (
                <tr>
                  <td colSpan={7} className="px-4 py-10 text-center text-slate-500">No IPOs match.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
