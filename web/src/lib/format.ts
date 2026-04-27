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
  operational: "bg-green-200 text-green-900 ring-green-500",
  watch: "bg-yellow-200 text-yellow-900 ring-yellow-500",
  alert: "bg-[#AB0520]/15 text-[#AB0520] ring-[#AB0520]/60",
};

// Tinted card background for plant tiles — fill is one step lighter than
// the border so the box reads as a clear shape on the page.
export const ALERT_CARD_BG: Record<AlertLevel, string> = {
  operational: "bg-green-200 border-green-600 hover:border-green-800",
  watch: "bg-yellow-200 border-yellow-600 hover:border-yellow-800",
  alert: "bg-[#AB0520]/20 border-[#AB0520]/70 hover:border-[#AB0520]",
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
