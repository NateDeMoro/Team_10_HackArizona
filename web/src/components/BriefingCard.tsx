import { AlertBadge } from "@/components/AlertBadge";
import type { BriefingResponse } from "@/lib/api";
import { fmtDate } from "@/lib/format";

type Props = { briefing: BriefingResponse };

export function BriefingCard({ briefing }: Props) {
  return (
    <section className="rounded-xl border border-[var(--ua-navy)]/15 bg-white p-4 shadow-sm">
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h2 className="text-sm font-semibold text-[var(--ua-navy)]">
          Forecast briefing
        </h2>
        <span className="text-xs text-[var(--ua-navy)]/60">
          as of {fmtDate(briefing.run_date)}
        </span>
      </div>

      <p className="text-sm leading-relaxed text-[var(--ua-navy)]">
        {briefing.headline}
      </p>

      <div className="mt-4">
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--ua-navy)]/70">
          Key risk days
        </h3>
        {briefing.risk_days.length === 0 ? (
          <span className="inline-flex items-center rounded-full bg-green-100 px-2.5 py-0.5 text-xs font-medium text-green-800 ring-1 ring-inset ring-green-300">
            All horizons green
          </span>
        ) : (
          <ul className="flex flex-col gap-2">
            {briefing.risk_days.map((day) => (
              <li
                key={`${day.target_date}-${day.horizon_days}`}
                className="flex flex-col gap-1 rounded-md bg-[var(--ua-navy)]/[0.03] p-2"
              >
                <div className="flex flex-wrap items-center gap-2 text-xs text-[var(--ua-navy)]/80">
                  <AlertBadge level={day.alert_level} />
                  <span className="font-medium">
                    {fmtDate(day.target_date)}
                  </span>
                  <span className="text-[var(--ua-navy)]/60">
                    ({day.point_pct.toFixed(1)}%)
                  </span>
                </div>
                <p className="text-xs leading-snug text-[var(--ua-navy)]/80">
                  {day.explanation}
                </p>
              </li>
            ))}
          </ul>
        )}
      </div>

      {briefing.drivers.length > 0 ? (
        <div className="mt-4">
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--ua-navy)]/70">
            What is driving this
          </h3>
          <ul className="list-disc space-y-1 pl-4 text-xs leading-snug text-[var(--ua-navy)]/80">
            {briefing.drivers.map((d, i) => (
              <li key={i}>{d}</li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="mt-4">
        <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-[var(--ua-navy)]/70">
          Bottom line
        </h3>
        <p className="text-xs italic leading-snug text-[var(--ua-navy)]/80">
          {briefing.outlook}
        </p>
      </div>

      {briefing.fallback ? (
        <div className="mt-3 rounded-md bg-yellow-100 px-2 py-1 text-[11px] text-yellow-800 ring-1 ring-inset ring-yellow-300">
          Numeric drift detected against the chart; treat narrative as
          approximate.
        </div>
      ) : null}

      <p className="mt-4 text-[10px] text-[var(--ua-navy)]/50">
        google.gemma-4
      </p>
    </section>
  );
}
