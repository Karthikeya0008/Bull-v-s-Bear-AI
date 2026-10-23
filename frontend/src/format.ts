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
  !v ? "text-slate-400" : v.includes("Bull") ? "text-bull-dark" : v.includes("Bear") ? "text-bear-dark" : "text-amber-600";

export const verdictBadge = (v: string | null | undefined) =>
  !v
    ? "border-slate-200 bg-slate-50 text-slate-500"
    : v.includes("Bull")
      ? "border-bull-line bg-bull-soft text-bull-dark"
      : v.includes("Bear")
        ? "border-bear-line bg-bear-soft text-bear-dark"
        : "border-amber-200 bg-amber-50 text-amber-700";

export const statusBadge: Record<string, string> = {
  upcoming: "border-sky-200 bg-sky-50 text-sky-700",
  open: "border-amber-200 bg-amber-50 text-amber-700",
  listed: "border-emerald-200 bg-emerald-50 text-emerald-700",
};
