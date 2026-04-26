"use client";

import { useEffect, useMemo, useState } from "react";

import { getBacktest, type BacktestRow } from "@/lib/api";
import { fmtDate, fmtPct } from "@/lib/format";

type Props = {
  plantId: string;
  dates: string[];
  highlights: string[];
};

export function ReplaySlider({ plantId, dates, highlights }: Props) {
  const initialIdx = useMemo(() => {
    // Default to the most-recent named highlight that exists in the date
    // range; otherwise the latest date.
    const lastHighlight = [...highlights].reverse().find((h) => dates.includes(h));
    if (lastHighlight) return dates.indexOf(lastHighlight);
    return dates.length - 1;
  }, [dates, highlights]);

  const [idx, setIdx] = useState(initialIdx);
  // Single state object tracks which as_of the current rows belong to so
  // the "loading" flag is derived from a mismatch rather than a synchronous
  // setState inside the effect body (react-hooks/set-state-in-effect).
  const [state, setState] = useState<{
    asOf: string | null;
    rows: BacktestRow[] | null;
    err: string | null;
  }>({ asOf: null, rows: null, err: null });

  const asOf = dates[idx] ?? "";

  useEffect(() => {
    if (!asOf) return;
    let cancelled = false;
    getBacktest(plantId, asOf)
      .then((res) => {
        if (cancelled) return;
        setState({ asOf, rows: res.rows, err: null });
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setState({
          asOf,
          rows: null,
          err: e instanceof Error ? e.message : String(e),
        });
      });
    return () => {
      cancelled = true;
    };
  }, [plantId, asOf]);

  const loading = state.asOf !== asOf;
  const rows = loading ? null : state.rows;
  const err = loading ? null : state.err;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-3">
        <input
          type="range"
          min={0}
          max={dates.length - 1}
          value={idx}
          onChange={(e) => setIdx(Number(e.target.value))}
          className="flex-1 accent-[var(--ua-red)]"
        />
        <span className="w-28 text-right font-mono text-sm text-[var(--ua-navy)]">
          {asOf}
        </span>
      </div>

      {highlights.length > 0 ? (
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="text-[var(--ua-navy)]/60">Heatwave highlights:</span>
          {highlights.map((d) => {
            const i = dates.indexOf(d);
            const disabled = i < 0;
            return (
              <button
                key={d}
                onClick={() => !disabled && setIdx(i)}
                disabled={disabled}
                className={
                  disabled
                    ? "cursor-not-allowed rounded-full border border-[var(--ua-navy)]/20 px-2 py-0.5 text-[var(--ua-navy)]/40"
                    : "rounded-full border border-[var(--ua-red)]/40 px-2 py-0.5 text-[var(--ua-red)] hover:bg-[var(--ua-red)] hover:text-white"
                }
              >
                {fmtDate(d)}
                {disabled ? " (no data)" : ""}
              </button>
            );
          })}
        </div>
      ) : null}

      <div className="overflow-hidden rounded-lg border border-[var(--ua-navy)]/15">
        <table className="w-full text-xs">
          <thead className="bg-[var(--ua-navy)] text-white">
            <tr>
              <th className="px-3 py-2 text-left font-medium">Horizon</th>
              <th className="px-3 py-2 text-left font-medium">Target</th>
              <th className="px-3 py-2 text-right font-medium">Predicted</th>
              <th className="px-3 py-2 text-right font-medium">Band</th>
              <th className="px-3 py-2 text-right font-medium">Actual</th>
              <th className="px-3 py-2 text-right font-medium">Δ</th>
            </tr>
          </thead>
          <tbody className="text-[var(--ua-navy)]">
            {loading ? (
              <tr>
                <td colSpan={6} className="px-3 py-4 text-center text-[var(--ua-navy)]/60">
                  Loading…
                </td>
              </tr>
            ) : err ? (
              <tr>
                <td colSpan={6} className="px-3 py-4 text-center text-[var(--ua-red)]">
                  {err}
                </td>
              </tr>
            ) : rows ? (
              rows.map((r) => {
                const delta =
                  r.actual_pct == null ? null : r.point_pct - r.actual_pct;
                return (
                  <tr
                    key={r.horizon_days}
                    className="border-t border-[var(--ua-navy)]/10"
                  >
                    <td className="px-3 py-1.5 font-mono">+{r.horizon_days}d</td>
                    <td className="px-3 py-1.5">{fmtDate(r.target_date)}</td>
                    <td className="px-3 py-1.5 text-right font-mono">
                      {fmtPct(r.point_pct)}
                    </td>
                    <td className="px-3 py-1.5 text-right font-mono text-[var(--ua-navy)]/60">
                      {fmtPct(r.band_low_pct)}–{fmtPct(r.band_high_pct)}
                    </td>
                    <td className="px-3 py-1.5 text-right font-mono">
                      {fmtPct(r.actual_pct)}
                    </td>
                    <td
                      className={
                        delta == null
                          ? "px-3 py-1.5 text-right font-mono text-[var(--ua-navy)]/40"
                          : Math.abs(delta) > 5
                            ? "px-3 py-1.5 text-right font-mono text-[var(--ua-red)]"
                            : "px-3 py-1.5 text-right font-mono text-[var(--ua-navy)]/70"
                      }
                    >
                      {delta == null
                        ? "—"
                        : `${delta >= 0 ? "+" : ""}${delta.toFixed(1)}`}
                    </td>
                  </tr>
                );
              })
            ) : null}
          </tbody>
        </table>
      </div>
    </div>
  );
}
