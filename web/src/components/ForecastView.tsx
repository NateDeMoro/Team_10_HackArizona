"use client";

import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { HorizonPrediction } from "@/lib/api";
import { CHART_NAVY, fmtDate, fmtPct } from "@/lib/format";

// Tier thresholds. Mirror schemas.UI_ALERT_THRESHOLD_PCT (90) and
// DIP_THRESHOLD_PCT (95).
const WATCH_PCT = 95;
const ALERT_PCT = 90;

const COLOR_LINE = "#0a0a0a";
const COLOR_GREEN = "#16a34a";
const COLOR_YELLOW = "#ca8a04";
const COLOR_RED = "#AB0520";

const Y_MIN = 60;
const Y_MAX = 102;

function tierColor(pct: number): string {
  if (pct >= WATCH_PCT) return COLOR_GREEN;
  if (pct >= ALERT_PCT) return COLOR_YELLOW;
  return COLOR_RED;
}

type Props = {
  forecast: HorizonPrediction[];
  runDate: string;
  height?: number;
};

// Above this point estimate the model is essentially saying "no derate";
// the dip-weighted training objective pulls predictions down into the
// 92-97 range even on days that will realize 100. Display floor pulls
// the line up to 100 in that regime so the chart looks like reality;
// the unclamped value is still in the tooltip.
const OPERATIONAL_DISPLAY_FLOOR = 95;
const OPERATIONAL_DISPLAY_CEILING = 100;

type Row = {
  date: string;
  forecast: number;
  forecastRaw: number;
};

function clampForDisplay(raw: number): number {
  return raw >= OPERATIONAL_DISPLAY_FLOOR ? OPERATIONAL_DISPLAY_CEILING : raw;
}

// Drop horizons whose target_date is already in the past. The ml
// inference pipeline anchors run_date at the latest available ERA5
// feature row, which lags ~7 days behind real time, so a fresh
// forecast still includes target_dates before today. Filtering here
// keeps the chart forward-looking without forcing a pipeline change.
function todayIso(): string {
  const d = new Date();
  const y = d.getUTCFullYear();
  const m = String(d.getUTCMonth() + 1).padStart(2, "0");
  const day = String(d.getUTCDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function buildRows(forecast: HorizonPrediction[]): Row[] {
  const today = todayIso();
  return forecast
    .slice()
    .filter((h) => h.target_date >= today)
    .sort((a, b) => a.target_date.localeCompare(b.target_date))
    .map((h) => ({
      date: h.target_date,
      forecast: clampForDisplay(h.point_pct),
      forecastRaw: h.point_pct,
    }));
}

function renderTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: readonly { payload?: Row }[];
  label?: string | number;
}) {
  if (!active || !payload || payload.length === 0) return null;
  const row = payload[0]?.payload;
  if (!row) return null;
  const color = tierColor(row.forecastRaw);
  return (
    <div className="rounded-md border border-[var(--ua-navy)]/20 bg-white px-3 py-2 text-xs shadow-md">
      <div className="font-semibold text-[var(--ua-navy)]">
        {typeof label === "string" ? fmtDate(label) : label}
      </div>
      <div className="font-mono" style={{ color }}>
        Forecast: {fmtPct(row.forecastRaw)}
        {row.forecastRaw >= OPERATIONAL_DISPLAY_FLOOR
          ? " (operational — shown at 100%)"
          : ""}
      </div>
    </div>
  );
}

type DotProps = { cx?: number; cy?: number; payload?: Row; index?: number };
function ForecastDot({ cx, cy, payload, index }: DotProps) {
  if (cx == null || cy == null || !payload) return null;
  return (
    <circle
      key={`fd-${index ?? payload.date}`}
      cx={cx}
      cy={cy}
      r={4}
      fill={tierColor(payload.forecastRaw)}
      stroke="#fff"
      strokeWidth={1}
    />
  );
}

export function ForecastView({ forecast, runDate, height = 300 }: Props) {
  const data = buildRows(forecast);
  if (data.length < 2) {
    return (
      <div className="flex h-32 items-center justify-center rounded-lg border border-dashed border-[var(--ua-navy)]/30 text-sm text-[var(--ua-navy)]/60">
        Not enough horizons to render the forecast.
      </div>
    );
  }
  return (
    <div style={{ width: "100%", height, minWidth: 0 }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 16, right: 24, bottom: 8, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e4e4e7" />
          <XAxis
            dataKey="date"
            tickFormatter={(v: string) => fmtDate(v)}
            minTickGap={32}
            tick={{ fontSize: 11, fill: CHART_NAVY }}
          />
          <YAxis
            domain={[Y_MIN, Y_MAX]}
            ticks={[60, 70, 80, 90, 95, 100]}
            tickFormatter={(v: number) => `${v}%`}
            tick={{ fontSize: 11, fill: CHART_NAVY }}
            width={48}
          />
          <Tooltip content={renderTooltip} />
          <ReferenceLine
            y={WATCH_PCT}
            stroke={COLOR_YELLOW}
            strokeOpacity={0.5}
            strokeDasharray="2 4"
            label={{
              value: "watch ≥ 95%",
              fill: COLOR_YELLOW,
              fillOpacity: 0.85,
              fontSize: 10,
              position: "insideBottomRight",
            }}
          />
          <ReferenceLine
            y={ALERT_PCT}
            stroke={COLOR_RED}
            strokeOpacity={0.5}
            strokeDasharray="2 4"
            label={{
              value: "alert < 90%",
              fill: COLOR_RED,
              fillOpacity: 0.85,
              fontSize: 10,
              position: "insideBottomRight",
            }}
          />
          <Line
            type="linear"
            dataKey="forecast"
            name="Forecast"
            stroke={COLOR_LINE}
            strokeWidth={1.5}
            dot={<ForecastDot />}
            activeDot={{ r: 5 }}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
      <p className="mt-2 text-xs text-[var(--ua-navy)]/60">
        Anchored at run date {fmtDate(runDate)} — 14-day forward outlook.
        Each day is a colored dot — green ≥ 95%, yellow 90–95%, red &lt; 90%.
      </p>
    </div>
  );
}
