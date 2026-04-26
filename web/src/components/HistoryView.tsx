"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { getHistoryMonth, type DipCategory, type HistoryPoint } from "@/lib/api";
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

const COLOR_LINE = "#0a0a0a";
const COLOR_GREEN = "#16a34a";
const COLOR_YELLOW = "#ca8a04";
const COLOR_RED = "#AB0520";
const COLOR_NON_WEATHER = "#7c3aed";

const CATEGORY_LABEL: Record<DipCategory, string> = {
  operational: "Operational",
  weather_dependent: "Weather-driven dip",
  non_weather_dependent: "Non-weather dip",
  refueling: "Refueling outage",
};

const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

type Row = HistoryPoint;

// Dot color combines the dip-category signal with the tier signal:
// non-weather dips and refueling have their own colors so they remain
// distinguishable; everything else is colored by capacity-factor tier
// (green/yellow/red) so an "operational ≥ 95" day reads green at a
// glance.
function dotColor(p: HistoryPoint): string {
  if (p.dip_category === "refueling") return COLOR_RED;
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
  const [month, setMonth] = useState(today.getMonth() + 1);
  const [points, setPoints] = useState<HistoryPoint[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setErr(null);
    getHistoryMonth(plantId, year, month)
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
  }, [plantId, year, month]);

  const yearOptions = useMemo(() => {
    const out: number[] = [];
    for (let y = today.getFullYear(); y >= EARLIEST_YEAR; y--) out.push(y);
    return out;
  }, [today]);

  const refuelSegments = useMemo(() => buildRefuelArea(points), [points]);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3 text-xs">
        <span className="font-medium text-[var(--ua-navy)]">Month:</span>
        <select
          value={month}
          onChange={(e) => setMonth(Number(e.target.value))}
          className="rounded-md border border-[var(--ua-navy)]/20 bg-white px-2 py-1 text-[var(--ua-navy)]"
        >
          {MONTHS.map((m, i) => (
            <option key={m} value={i + 1}>
              {m}
            </option>
          ))}
        </select>
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
            No data for {MONTHS[month - 1]} {year}.
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart
              data={points}
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
              {refuelSegments.length > 0 ? (
                <Area
                  data={refuelSegments}
                  dataKey="value"
                  type="linear"
                  fill={COLOR_RED}
                  fillOpacity={0.18}
                  stroke="none"
                  isAnimationActive={false}
                  legendType="none"
                />
              ) : null}
              <Line
                type="linear"
                dataKey="power_pct"
                name="Actual"
                stroke={COLOR_LINE}
                strokeWidth={1.5}
                dot={<ColoredDot />}
                activeDot={{ r: 5 }}
                isAnimationActive={false}
              />
            </ComposedChart>
          </ResponsiveContainer>
        )}
      </div>

      <p className="text-xs text-[var(--ua-navy)]/60">
        Each day is a colored dot — green ≥ 95%, yellow 90–95%, red &lt; 90%.
        Violet marks non-weather-driven dips (model predicted ≥ 95% but
        realization fell below 90%). Refueling outages pin to 0% and shade
        red.
      </p>
    </div>
  );
}

function buildRefuelArea(
  points: HistoryPoint[] | null,
): { date: string; value: number | null }[] {
  if (!points) return [];
  return points.map((p) => ({
    date: p.date,
    value: p.is_outage ? Y_MAX : null,
  }));
}

function Legend() {
  const items: { color: string; label: string }[] = [
    { color: COLOR_GREEN, label: "Operational ≥ 95%" },
    { color: COLOR_YELLOW, label: "Watch 90–95%" },
    { color: COLOR_RED, label: "Alert < 90%" },
    { color: COLOR_NON_WEATHER, label: "Non-weather dip" },
  ];
  return (
    <div className="ml-auto flex flex-wrap items-center gap-3 text-[var(--ua-navy)]/70">
      {items.map((it) => (
        <span key={it.label} className="inline-flex items-center gap-1">
          <span
            className="inline-block h-2 w-2 rounded-full"
            style={{ background: it.color }}
          />
          {it.label}
        </span>
      ))}
      <span className="inline-flex items-center gap-1">
        <span
          className="inline-block h-2 w-3 rounded-sm"
          style={{ background: COLOR_RED, opacity: 0.35 }}
        />
        Refueling
      </span>
    </div>
  );
}
