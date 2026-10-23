export const fmtNum = (v: number | null | undefined, digits = 2) =>
  v === null || v === undefined ? "—" : v.toLocaleString("en-IN", { maximumFractionDigits: digits });

export function fmtMetric(value: number | null, unit: string): string {
  if (value === null) return "—";
  if (unit === "%") return `${fmtNum(value, 1)}%`;
  if (unit === "x") return `${fmtNum(value, 2)}x`;
  if (unit === "INR mn") return `₹${fmtNum(value / 10, 0)} cr`;
  return fmtNum(value, 2);
}

export const fmtDate = (d: string | null) =>
  d ? new Date(d).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : "—";

export const verdictColor = (v: string | null | undefined) =>
  !v ? "text-slate-400" : v.includes("Bull") ? "text-bull" : v.includes("Bear") ? "text-bear" : "text-amber-300";

export const statusBadge: Record<string, string> = {
  upcoming: "bg-sky-500/15 text-sky-300 border-sky-500/30",
  open: "bg-amber-500/15 text-amber-300 border-amber-500/30",
  listed: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
};
