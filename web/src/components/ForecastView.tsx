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
import { CHART_NAVY, CHART_RED, fmtDate, fmtPct } from "@/lib/format";

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

function buildRows(forecast: HorizonPrediction[]): Row[] {
  return forecast
    .slice()
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
  return (
    <div className="rounded-md border border-[var(--ua-navy)]/20 bg-white px-3 py-2 text-xs shadow-md">
      <div className="font-semibold text-[var(--ua-navy)]">
        {typeof label === "string" ? fmtDate(label) : label}
      </div>
      <div className="font-mono text-[var(--ua-red)]">
        Forecast: {fmtPct(row.forecastRaw)}
        {row.forecastRaw >= OPERATIONAL_DISPLAY_FLOOR
          ? " (operational — shown at 100%)"
          : ""}
      </div>
    </div>
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
    <div style={{ width: "100%", height }}>
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
            domain={[60, 102]}
            ticks={[60, 70, 80, 90, 95, 100]}
            tickFormatter={(v: number) => `${v}%`}
            tick={{ fontSize: 11, fill: CHART_NAVY }}
            width={48}
          />
          <Tooltip content={renderTooltip} />
          <ReferenceLine
            y={95}
            stroke={CHART_NAVY}
            strokeOpacity={0.4}
            strokeDasharray="2 4"
            label={{
              value: "watch ≥ 95%",
              fill: CHART_NAVY,
              fillOpacity: 0.7,
              fontSize: 10,
              position: "insideBottomRight",
            }}
          />
          <Line
            type="monotone"
            dataKey="forecast"
            name="Forecast"
            stroke={CHART_RED}
            strokeWidth={2.5}
            dot={{ r: 3, fill: CHART_RED }}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
      <p className="mt-2 text-xs text-[var(--ua-navy)]/60">
        Anchored at run date {fmtDate(runDate)} — 14-day forward outlook.
      </p>
    </div>
  );
}
