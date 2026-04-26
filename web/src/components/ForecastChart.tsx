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

import type { ActualPoint, HorizonPrediction } from "@/lib/api";
import { CHART_NAVY, CHART_RED, fmtDate, fmtPct } from "@/lib/format";

type Props = {
  actuals: ActualPoint[];
  forecast: HorizonPrediction[];
  runDate: string;
  height?: number;
};

// Above this point estimate the model is essentially saying "no
// derate"; the dip-weighted training objective pulls predictions down
// into the 92-97 range even on days that will realize 100. Displaying
// the raw point makes the chart look pessimistic against actuals; the
// honest visual is a flat 100 in the operational regime, with the
// curve only dropping when the model crosses into watch (<95) or
// alert (<90). The unclamped value is still surfaced in the tooltip.
const OPERATIONAL_DISPLAY_FLOOR = 95;
const OPERATIONAL_DISPLAY_CEILING = 100;

type Row = {
  date: string;
  actual: number | null;
  forecast: number | null;
  forecastRaw: number | null;
};

function clampForDisplay(raw: number): number {
  return raw >= OPERATIONAL_DISPLAY_FLOOR ? OPERATIONAL_DISPLAY_CEILING : raw;
}

function buildRows(
  actuals: ActualPoint[],
  forecast: HorizonPrediction[],
  runDate: string,
): Row[] {
  const byDate = new Map<string, Row>();

  for (const a of actuals) {
    byDate.set(a.date, {
      date: a.date,
      actual: a.power_pct,
      forecast: null,
      forecastRaw: null,
    });
  }

  // Anchor the forecast line at the last realized actual so the visual
  // transition across the run-date divider is continuous (no gap).
  const lastActual = [...actuals]
    .reverse()
    .find((a): a is ActualPoint & { power_pct: number } => a.power_pct != null);
  if (lastActual) {
    const row = byDate.get(lastActual.date);
    if (row) {
      row.forecast = lastActual.power_pct;
      row.forecastRaw = lastActual.power_pct;
    }
  }

  // Stamp the run_date itself as a "join" point so the forecast line
  // begins exactly at the divider even if `actuals` doesn't include it.
  if (!byDate.has(runDate) && lastActual) {
    byDate.set(runDate, {
      date: runDate,
      actual: lastActual.power_pct,
      forecast: lastActual.power_pct,
      forecastRaw: lastActual.power_pct,
    });
  }

  for (const h of forecast) {
    const existing = byDate.get(h.target_date);
    const display = clampForDisplay(h.point_pct);
    if (existing) {
      existing.forecast = display;
      existing.forecastRaw = h.point_pct;
    } else {
      byDate.set(h.target_date, {
        date: h.target_date,
        actual: null,
        forecast: display,
        forecastRaw: h.point_pct,
      });
    }
  }

  return [...byDate.values()].sort((a, b) => a.date.localeCompare(b.date));
}

// Recharts 3.x tooltip content can be a render function; we use that form
// so we don't have to satisfy the full TooltipContentProps interface as a
// JSX element (which trips strict TS).
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
      {row.actual != null ? (
        <div className="font-mono text-[var(--ua-navy)]">
          Actual: {fmtPct(row.actual)}
        </div>
      ) : null}
      {row.forecastRaw != null ? (
        <div className="font-mono text-[var(--ua-red)]">
          Forecast: {fmtPct(row.forecastRaw)}
          {row.forecastRaw >= OPERATIONAL_DISPLAY_FLOOR
            ? " (operational — shown at 100%)"
            : ""}
        </div>
      ) : null}
    </div>
  );
}

export function ForecastChart({
  actuals,
  forecast,
  runDate,
  height = 300,
}: Props) {
  const data = buildRows(actuals, forecast, runDate);
  if (data.length < 2) {
    return (
      <div className="flex h-32 items-center justify-center rounded-lg border border-dashed border-zinc-300 text-sm text-zinc-500">
        Not enough data to render the forecast chart.
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
            x={runDate}
            stroke={CHART_RED}
            strokeDasharray="3 3"
            label={{
              value: `run ${fmtDate(runDate)}`,
              fill: CHART_RED,
              fontSize: 10,
              position: "insideTopRight",
            }}
          />
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
            dataKey="actual"
            name="Actual"
            stroke={CHART_NAVY}
            strokeWidth={2.5}
            dot={false}
            connectNulls={false}
            isAnimationActive={false}
          />
          <Line
            type="monotone"
            dataKey="forecast"
            name="Forecast"
            stroke={CHART_RED}
            strokeWidth={2.5}
            strokeDasharray="5 3"
            dot={{ r: 3, fill: CHART_RED }}
            connectNulls
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
