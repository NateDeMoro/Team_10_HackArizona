import type { FeatureContribution } from "@/lib/api";
import { featureLabel } from "@/lib/featureLabels";
import { fmtNumber } from "@/lib/format";

type Props = {
  features: FeatureContribution[];
  baselinePct: number;
  pointPct: number;
  topN?: number;
  compact?: boolean;
};

/** Horizontal bars of signed SHAP contributions in capacity-factor pp.
 *  Positive (navy) push the prediction up, negative (red) push it down.
 *  `compact` narrows the label column for use in the smaller side panel. */
export function AttributionBars({
  features,
  baselinePct,
  pointPct,
  topN = 5,
  compact = false,
}: Props) {
  const top = features.slice(0, topN);
  const max = Math.max(0.01, ...top.map((f) => Math.abs(f.contribution_pct)));
  const labelWidth = compact ? "w-36" : "w-56";
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-baseline justify-between text-xs text-[var(--ua-navy)]/90">
        <span>
          Baseline{" "}
          <span className="font-mono text-[var(--ua-navy)]">
            {fmtNumber(baselinePct, 1)}
          </span>{" "}
          → Point{" "}
          <span className="font-mono text-[var(--ua-navy)]">
            {fmtNumber(pointPct, 1)}
          </span>
        </span>
        <span>top {topN} features</span>
      </div>
      <ul className="flex flex-col gap-2">
        {top.map((f) => {
          const widthPct = (Math.abs(f.contribution_pct) / max) * 50;
          const positive = f.contribution_pct >= 0;
          return (
            <li key={f.feature} className="flex items-center gap-2 text-xs">
              <span
                className={`${labelWidth} truncate text-[var(--ua-navy)]`}
                title={f.feature}
              >
                {featureLabel(f.feature)}
              </span>
              <div className="relative flex h-4 flex-1 items-center">
                <div className="absolute left-1/2 top-0 h-full w-px bg-[var(--ua-navy)]/20" />
                <div
                  className={
                    positive
                      ? "absolute left-1/2 h-3 rounded-r bg-[var(--ua-navy)]"
                      : "absolute right-1/2 h-3 rounded-l bg-[var(--ua-red)]"
                  }
                  style={{ width: `${widthPct}%` }}
                />
              </div>
              <span className="w-14 text-right font-mono text-[var(--ua-navy)]">
                {f.contribution_pct >= 0 ? "+" : ""}
                {fmtNumber(f.contribution_pct, 2)}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
