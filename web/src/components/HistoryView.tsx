"use client";

import { useEffect, useMemo, useState } from "react";
import {
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { getHistoryYear, type DipCategory, type HistoryPoint } from "@/lib/api";
import { CHART_NAVY, fmtDate, fmtPct } from "@/lib/format";

type Props = {
  plantId: string;
  height?: number;
};

const EARLIEST_YEAR = 2005;

const Y_MIN = 0;
const Y_MAX = 102;

const WATCH_PCT = 95;
const ALERT_PCT = 90;

const COLOR_LINE = "#22c55e";
const COLOR_GREEN = "#22c55e";
const COLOR_YELLOW = "#ca8a04";
const COLOR_RED = "#AB0520";
const COLOR_REFUEL = "#1d4ed8";
const COLOR_NON_WEATHER = "#d946ef";

const CATEGORY_LABEL: Record<DipCategory, string> = {
  operational: "Operational",
  weather_dependent: "Weather-driven dip",
  non_weather_dependent: "Non-weather dip",
  refueling: "Refueling outage",
  post_refuel_recovery: "Post-refuel recovery",
};

type Row = HistoryPoint;

// Dot color combines the dip-category signal with the tier signal:
// non-weather dips and refueling have their own colors so they remain
// distinguishable; everything else is colored by capacity-factor tier
// (green/yellow/red) so an "operational ≥ 95" day reads green at a
// glance.
function dotColor(p: HistoryPoint): string {
  if (p.dip_category === "refueling") return COLOR_REFUEL;
  if (p.dip_category === "post_refuel_recovery") return COLOR_REFUEL;
  if (p.dip_category === "non_weather_dependent") return COLOR_NON_WEATHER;
  if (p.power_pct >= WATCH_PCT) return COLOR_GREEN;
  if (p.power_pct >= ALERT_PCT) return COLOR_YELLOW;
  return COLOR_RED;
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
      {row.is_outage ? (
        <div className="font-mono text-[var(--ua-red)]">
          Refueling outage (plotted at 0%)
        </div>
      ) : (
        <div className="font-mono text-[var(--ua-navy)]">
          Actual: {fmtPct(row.power_pct)}
        </div>
      )}
      {row.prediction_pct != null ? (
        <div className="font-mono text-[var(--ua-navy)]/70">
          Model (h=7): {fmtPct(row.prediction_pct)}
        </div>
      ) : null}
      <div className="font-mono" style={{ color: dotColor(row) }}>
        {CATEGORY_LABEL[row.dip_category]}
      </div>
    </div>
  );
}

type DotProps = { cx?: number; cy?: number; payload?: HistoryPoint; index?: number };
function ColoredDot({ cx, cy, payload, index }: DotProps) {
  if (cx == null || cy == null || !payload) return null;
  // Skip dots for the "dense" categories so the line speaks for them:
  // green operational stretches and the blue refueling+recovery stretches.
  // Keep dots only for the rare/interesting events (yellow watch, magenta
  // non-weather dip).
  if (payload.dip_category === "refueling") return null;
  if (payload.dip_category === "post_refuel_recovery") return null;
  if (
    payload.dip_category === "operational" &&
    payload.power_pct >= WATCH_PCT
  ) {
    return null;
  }
  return (
    <circle
      key={`hd-${index ?? payload.date}`}
      cx={cx}
      cy={cy}
      r={3.5}
      fill={dotColor(payload)}
      stroke="#fff"
      strokeWidth={1}
    />
  );
}

export function HistoryView({ plantId, height = 300 }: Props) {
  const today = useMemo(() => new Date(), []);
  const [year, setYear] = useState(today.getFullYear());
  const [points, setPoints] = useState<HistoryPoint[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setErr(null);
    getHistoryYear(plantId, year)
      .then((res) => {
        if (cancelled) return;
        setPoints(res.points);
        setLoading(false);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setErr(e instanceof Error ? e.message : String(e));
        setPoints(null);
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [plantId, year]);

  const yearOptions = useMemo(() => {
    const out: number[] = [];
    for (let y = today.getFullYear(); y >= EARLIEST_YEAR; y--) out.push(y);
    return out;
  }, [today]);

  // Split the line into two series so the refueling + recovery stretches
  // render in blue while the rest stays green. A day belongs to the blue
  // series if it is an outage OR a post-refuel-recovery day; each segment
  // also includes its boundary point (the immediately adjacent neighbor)
  // so the two lines visually connect without a gap at the transition.
  const chartData = useMemo(() => {
    const pts = points ?? [];
    const isBlue = (p?: HistoryPoint) =>
      !!p && (p.is_outage || p.dip_category === "post_refuel_recovery");
    return pts.map((p, i) => {
      const prev = pts[i - 1];
      const next = pts[i + 1];
      const blueHere = isBlue(p);
      const blueAdj = isBlue(prev) || isBlue(next);
      return {
        ...p,
        value_main: blueHere ? null : p.power_pct,
        value_refuel: blueHere || blueAdj ? p.power_pct : null,
      };
    });
  }, [points]);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3 text-xs">
        <span className="font-medium text-[var(--ua-navy)]">Year:</span>
        <select
          value={year}
          onChange={(e) => setYear(Number(e.target.value))}
          className="rounded-md border border-[var(--ua-navy)]/20 bg-white px-2 py-1 text-[var(--ua-navy)]"
        >
          {yearOptions.map((y) => (
            <option key={y} value={y}>
              {y}
            </option>
          ))}
        </select>
        <Legend />
      </div>

      <div style={{ width: "100%", height }}>
        {err ? (
          <div className="flex h-full items-center justify-center text-sm text-[var(--ua-red)]">
            {err}
          </div>
        ) : loading ? (
          <div className="flex h-full items-center justify-center text-sm text-[var(--ua-navy)]/60">
            Loading…
          </div>
        ) : !points || points.length < 2 ? (
          <div className="flex h-full items-center justify-center rounded-lg border border-dashed border-[var(--ua-navy)]/30 text-sm text-[var(--ua-navy)]/60">
            No data for {year}.
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart
              data={chartData}
              margin={{ top: 16, right: 24, bottom: 8, left: 0 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#e4e4e7" />
              <XAxis
                dataKey="date"
                tickFormatter={(v: string) => fmtDate(v)}
                minTickGap={32}
                tick={{ fontSize: 11, fill: CHART_NAVY }}
              />
              <YAxis
                domain={[Y_MIN, Y_MAX]}
                ticks={[0, 25, 50, 75, 90, 95, 100]}
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
              />
              <ReferenceLine
                y={ALERT_PCT}
                stroke={COLOR_RED}
                strokeOpacity={0.5}
                strokeDasharray="2 4"
              />
              <Line
                type="linear"
                dataKey="value_main"
                name="Actual"
                stroke={COLOR_LINE}
                strokeWidth={1.5}
                dot={<ColoredDot />}
                activeDot={{ r: 5 }}
                isAnimationActive={false}
                connectNulls={false}
              />
              <Line
                type="linear"
                dataKey="value_refuel"
                name="Refueling"
                stroke={COLOR_REFUEL}
                strokeWidth={3}
                dot={false}
                activeDot={{ r: 5 }}
                isAnimationActive={false}
                connectNulls={false}
                legendType="none"
              />
            </ComposedChart>
          </ResponsiveContainer>
        )}
      </div>

      <p className="text-xs text-[var(--ua-navy)]/60">
        Operational days (≥ 95%) draw as the green trend line. Yellow dots
        mark watch days (90–95%); magenta dots mark non-weather-driven dips
        (model predicted ≥ 95% but realization fell below 90%). Refueling
        outages and the reactor ramp-back that follows render as a bold
        blue line until the plant returns to ≥ 95%.
      </p>
    </div>
  );
}

function Legend() {
  return (
    <div className="ml-auto flex flex-wrap items-center gap-3 text-[var(--ua-navy)]/70">
      <span className="inline-flex items-center gap-1">
        <span
          className="inline-block h-0.5 w-4"
          style={{ background: COLOR_GREEN }}
        />
        Operational ≥ 95%
      </span>
      <span className="inline-flex items-center gap-1">
        <span
          className="inline-block h-2 w-2 rounded-full"
          style={{ background: COLOR_YELLOW }}
        />
        Watch 90–95%
      </span>
      <span className="inline-flex items-center gap-1">
        <span
          className="inline-block h-2 w-2 rounded-full"
          style={{ background: COLOR_NON_WEATHER }}
        />
        Non-weather dip
      </span>
      <span className="inline-flex items-center gap-1">
        <span
          className="inline-block h-1 w-4"
          style={{ background: COLOR_REFUEL }}
        />
        Refueling + recovery
      </span>
    </div>
  );
}
