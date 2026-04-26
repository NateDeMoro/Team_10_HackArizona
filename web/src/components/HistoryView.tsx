"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
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

// Earliest year the labels parquet reaches (NRC daily power-status
// archive starts 2005). Upper bound is the current year.
const EARLIEST_YEAR = 2005;

// Y-axis stays fixed [0, 102]. Gradient stops below are computed off this
// domain — change here, change everywhere.
const Y_MIN = 0;
const Y_MAX = 102;

// Tier thresholds. Mirror schemas.UI_ALERT_THRESHOLD_PCT (90) and
// DIP_THRESHOLD_PCT (95).
const WATCH_PCT = 95;
const ALERT_PCT = 90;

const COLOR_GREEN = "#16a34a";
const COLOR_YELLOW = "#ca8a04";
const COLOR_RED = "#AB0520";
const COLOR_NON_WEATHER = "#7c3aed"; // violet — distinct from the gradient

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

function gradientStop(pct: number): string {
  // Fraction down from the top of the chart in svg space.
  const frac = (Y_MAX - pct) / (Y_MAX - Y_MIN);
  return `${(frac * 100).toFixed(2)}%`;
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
  const categoryColor =
    row.dip_category === "operational"
      ? COLOR_GREEN
      : row.dip_category === "non_weather_dependent"
        ? COLOR_NON_WEATHER
        : COLOR_RED;
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
      <div className="font-mono" style={{ color: categoryColor }}>
        {CATEGORY_LABEL[row.dip_category]}
      </div>
    </div>
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
  const nonWeatherDots = useMemo(
    () =>
      (points ?? []).filter(
        (p) => p.dip_category === "non_weather_dependent",
      ),
    [points],
  );
  const weatherDipDots = useMemo(
    () =>
      (points ?? []).filter((p) => p.dip_category === "weather_dependent"),
    [points],
  );

  const gradientId = "history-stroke-grad";

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
              <defs>
                <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={COLOR_GREEN} />
                  <stop offset={gradientStop(WATCH_PCT)} stopColor={COLOR_GREEN} />
                  <stop offset={gradientStop(WATCH_PCT)} stopColor={COLOR_YELLOW} />
                  <stop offset={gradientStop(ALERT_PCT)} stopColor={COLOR_YELLOW} />
                  <stop offset={gradientStop(ALERT_PCT)} stopColor={COLOR_RED} />
                  <stop offset="100%" stopColor={COLOR_RED} />
                </linearGradient>
              </defs>
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
                stroke={`url(#${gradientId})`}
                strokeWidth={2.25}
                dot={false}
                isAnimationActive={false}
              />
              {weatherDipDots.length > 0 ? (
                <Scatter
                  data={weatherDipDots}
                  dataKey="power_pct"
                  fill={COLOR_RED}
                  shape="circle"
                  isAnimationActive={false}
                  legendType="none"
                />
              ) : null}
              {nonWeatherDots.length > 0 ? (
                <Scatter
                  data={nonWeatherDots}
                  dataKey="power_pct"
                  fill={COLOR_NON_WEATHER}
                  shape="triangle"
                  isAnimationActive={false}
                  legendType="none"
                />
              ) : null}
            </ComposedChart>
          </ResponsiveContainer>
        )}
      </div>

      <p className="text-xs text-[var(--ua-navy)]/60">
        Line color tracks tier (green ≥ 95%, yellow 90–95%, red &lt; 90%).
        Refueling outages are pinned to 0% and shaded red. Triangles mark
        non-weather-driven dips — days the model predicted full power but
        realization fell below 90%.
      </p>
    </div>
  );
}

// Refueling shading is rendered as an Area whose value is Y_MAX on
// outage days and null elsewhere. Recharts stops drawing when value is
// null, which is exactly the segment behavior we want.
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
  const items: { color: string; label: string; shape: "line" | "tri" | "dot" | "swatch" }[] = [
    { color: COLOR_GREEN, label: "Operational ≥ 95%", shape: "line" },
    { color: COLOR_YELLOW, label: "Watch 90–95%", shape: "line" },
    { color: COLOR_RED, label: "Alert < 90%", shape: "line" },
    { color: COLOR_NON_WEATHER, label: "Non-weather dip", shape: "tri" },
    { color: COLOR_RED, label: "Refueling", shape: "swatch" },
  ];
  return (
    <div className="ml-auto flex flex-wrap items-center gap-3 text-[var(--ua-navy)]/70">
      {items.map((it) => (
        <span key={it.label} className="inline-flex items-center gap-1">
          {it.shape === "line" ? (
            <span
              className="inline-block h-[2px] w-4"
              style={{ background: it.color }}
            />
          ) : it.shape === "tri" ? (
            <span
              className="inline-block h-0 w-0"
              style={{
                borderLeft: "4px solid transparent",
                borderRight: "4px solid transparent",
                borderBottom: `7px solid ${it.color}`,
              }}
            />
          ) : it.shape === "swatch" ? (
            <span
              className="inline-block h-2 w-3 rounded-sm"
              style={{ background: it.color, opacity: 0.35 }}
            />
          ) : (
            <span
              className="inline-block h-2 w-2 rounded-full"
              style={{ background: it.color }}
            />
          )}
          {it.label}
        </span>
      ))}
    </div>
  );
}
