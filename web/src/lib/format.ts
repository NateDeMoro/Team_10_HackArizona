import type { AlertLevel } from "@/lib/api";

export const ALERT_COPY: Record<AlertLevel, string> = {
  operational: "Operational",
  watch: "Watch",
  alert: "Alert",
};

// Alert tier semantics stay green/yellow/red (universal traffic-light) so
// the operator instinct holds regardless of branding.
export const ALERT_HEX: Record<AlertLevel, string> = {
  operational: "#16a34a", // green-600
  watch: "#ca8a04",       // yellow-600
  alert: "#AB0520",       // UA Cardinal Red — doubles as the brand red
};

export const ALERT_BG: Record<AlertLevel, string> = {
  operational: "bg-green-100 text-green-800 ring-green-300",
  watch: "bg-yellow-100 text-yellow-800 ring-yellow-300",
  alert: "bg-[#AB0520]/10 text-[#AB0520] ring-[#AB0520]/40",
};

// Brand chart colors (used by ForecastChart).
export const CHART_NAVY = "#0C234B"; // actuals line
export const CHART_RED = "#AB0520";  // forecast line + run-date divider

export function fmtDate(iso: string): string {
  // ISO date -> "Apr 18". Locale-independent so SSR + client agree.
  const d = new Date(`${iso}T00:00:00Z`);
  return d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

export function fmtPct(v: number | null | undefined, digits = 1): string {
  if (v == null || Number.isNaN(v)) return "—";
  return `${v.toFixed(digits)}%`;
}

export function fmtNumber(v: number | null | undefined, digits = 1): string {
  if (v == null || Number.isNaN(v)) return "—";
  return v.toFixed(digits);
}
