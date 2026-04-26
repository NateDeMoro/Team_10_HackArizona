"use client";

import { useEffect, useMemo, useState } from "react";
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

import {
  getActuals,
  getBacktestSeries,
  type ActualPoint,
  type BacktestSeriesPoint,
} from "@/lib/api";
import { CHART_NAVY, CHART_RED, fmtDate, fmtNumber, fmtPct } from "@/lib/format";

type Props = {
  plantId: string;
  height?: number;
};

const WINDOWS = [30, 90, 180, 365] as const;
type Window = (typeof WINDOWS)[number];
const OVERLAY_HORIZON = 7;

type Row = {
  date: string;
  actual: number | null;
  prediction: number | null;
};

type Snapshot = {
  window: Window;
  overlay: boolean;
  actuals: ActualPoint[] | null;
  predictions: BacktestSeriesPoint[] | null;
  err: string | null;
};

function buildRows(
  actuals: ActualPoint[] | null,
  predictions: BacktestSeriesPoint[] | null,
): Row[] {
  const byDate = new Map<string, Row>();
  for (const a of actuals ?? []) {
    byDate.set(a.date, { date: a.date, actual: a.power_pct, prediction: null });
  }
  for (const p of predictions ?? []) {
    const row = byDate.get(p.date);
    if (row) {
      row.prediction = p.point_pct;
    } else {
      byDate.set(p.date, {
        date: p.date,
        actual: p.actual_pct,
        prediction: p.point_pct,
      });
    }
  }
  return [...byDate.values()].sort((a, b) => a.date.localeCompare(b.date));
}

/** MAE on the dates where both the actual (from backtest_results) and the
 *  predicted point are present. Uses the backtest series' own actual
 *  column rather than the labels parquet to keep both sides on the same
 *  filter (outage exclusion etc.). */
function overlapMae(predictions: BacktestSeriesPoint[]): {
  mae: number | null;
  n: number;
} {
  const both = predictions.filter(
    (p): p is BacktestSeriesPoint & { actual_pct: number } =>
      p.actual_pct != null,
  );
  if (both.length === 0) return { mae: null, n: 0 };
  const sum = both.reduce((acc, p) => acc + Math.abs(p.point_pct - p.actual_pct), 0);
  return { mae: sum / both.length, n: both.length };
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
      {row.actual != null ? (
        <div className="font-mono text-[var(--ua-navy)]">
          Actual: {fmtPct(row.actual)}
        </div>
      ) : null}
      {row.prediction != null ? (
        <div className="font-mono text-[var(--ua-red)]">
          Predicted (h={OVERLAY_HORIZON}): {fmtPct(row.prediction)}
        </div>
      ) : null}
    </div>
  );
}

export function HistoryView({ plantId, height = 300 }: Props) {
  const [window, setWindow] = useState<Window>(90);
  const [overlay, setOverlay] = useState(false);
  // Single state object so the loading flag derives from a snapshot
  // mismatch instead of a synchronous setState in the effect (eslint
  // react-hooks/set-state-in-effect).
  const [snap, setSnap] = useState<Snapshot>({
    window: 90,
    overlay: false,
    actuals: null,
    predictions: null,
    err: null,
  });

  useEffect(() => {
    let cancelled = false;
    const tasks: Promise<unknown>[] = [getActuals(plantId, window)];
    if (overlay) tasks.push(getBacktestSeries(plantId, OVERLAY_HORIZON, window));
    Promise.all(tasks)
      .then((results) => {
        if (cancelled) return;
        const [actualsRes, seriesRes] = results as [
          { points: ActualPoint[] },
          { points: BacktestSeriesPoint[] } | undefined,
        ];
        setSnap({
          window,
          overlay,
          actuals: actualsRes.points,
          predictions: seriesRes?.points ?? null,
          err: null,
        });
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setSnap({
          window,
          overlay,
          actuals: null,
          predictions: null,
          err: e instanceof Error ? e.message : String(e),
        });
      });
    return () => {
      cancelled = true;
    };
  }, [plantId, window, overlay]);

  const loading = snap.window !== window || snap.overlay !== overlay;
  const rows = useMemo(
    () => (loading ? [] : buildRows(snap.actuals, snap.predictions)),
    [loading, snap.actuals, snap.predictions],
  );
  const mae = useMemo(
    () => (snap.predictions ? overlapMae(snap.predictions) : { mae: null, n: 0 }),
    [snap.predictions],
  );

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3 text-xs">
        <span className="font-medium text-[var(--ua-navy)]">Window:</span>
        <div className="inline-flex overflow-hidden rounded-md border border-[var(--ua-navy)]/20">
          {WINDOWS.map((w) => (
            <button
              key={w}
              onClick={() => setWindow(w)}
              className={
                w === window
                  ? "bg-[var(--ua-navy)] px-3 py-1 font-medium text-white"
                  : "bg-white px-3 py-1 text-[var(--ua-navy)] hover:bg-[var(--ua-navy)]/[0.05]"
              }
            >
              {w}d
            </button>
          ))}
        </div>
        <label className="ml-2 inline-flex cursor-pointer items-center gap-2 text-[var(--ua-navy)]">
          <input
            type="checkbox"
            checked={overlay}
            onChange={(e) => setOverlay(e.target.checked)}
            className="h-4 w-4 accent-[var(--ua-red)]"
          />
          Overlay model predictions for this period (h={OVERLAY_HORIZON})
        </label>
        {overlay && mae.mae != null ? (
          <span className="inline-flex items-center gap-1 rounded-full bg-[var(--ua-red)]/10 px-2 py-0.5 font-mono text-[var(--ua-red)]">
            MAE {fmtNumber(mae.mae, 1)} pp · n={mae.n}
          </span>
        ) : null}
      </div>

      <div style={{ width: "100%", height }}>
        {snap.err ? (
          <div className="flex h-full items-center justify-center text-sm text-[var(--ua-red)]">
            {snap.err}
          </div>
        ) : loading ? (
          <div className="flex h-full items-center justify-center text-sm text-[var(--ua-navy)]/60">
            Loading…
          </div>
        ) : rows.length < 2 ? (
          <div className="flex h-full items-center justify-center rounded-lg border border-dashed border-[var(--ua-navy)]/30 text-sm text-[var(--ua-navy)]/60">
            Not enough data in this window.
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart
              data={rows}
              margin={{ top: 16, right: 24, bottom: 8, left: 0 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#e4e4e7" />
              <XAxis
                dataKey="date"
                tickFormatter={(v: string) => fmtDate(v)}
                minTickGap={48}
                tick={{ fontSize: 11, fill: CHART_NAVY }}
              />
              <YAxis
                domain={[0, 102]}
                ticks={[0, 25, 50, 75, 95, 100]}
                tickFormatter={(v: number) => `${v}%`}
                tick={{ fontSize: 11, fill: CHART_NAVY }}
                width={48}
              />
              <Tooltip content={renderTooltip} />
              <ReferenceLine
                y={95}
                stroke={CHART_NAVY}
                strokeOpacity={0.3}
                strokeDasharray="2 4"
              />
              <Line
                type="monotone"
                dataKey="actual"
                name="Actual"
                stroke={CHART_NAVY}
                strokeWidth={2}
                dot={false}
                connectNulls={false}
                isAnimationActive={false}
              />
              {overlay ? (
                <Line
                  type="monotone"
                  dataKey="prediction"
                  name="Predicted"
                  stroke={CHART_RED}
                  strokeWidth={2}
                  dot={false}
                  connectNulls
                  isAnimationActive={false}
                />
              ) : null}
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>

      {overlay ? (
        <p className="text-xs text-[var(--ua-navy)]/60">
          Backtest coverage starts 2023-01-01. Earlier dates render
          actuals only.
        </p>
      ) : null}
    </div>
  );
}
