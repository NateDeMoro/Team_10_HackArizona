import type { WeatherInputPoint } from "@/lib/api";
import { fmtNumber } from "@/lib/format";

type Props = { points: WeatherInputPoint[] };

type Series = {
  label: string;
  unit: string;
  values: (number | null)[];
};

function Sparkline({ values, color }: { values: (number | null)[]; color: string }) {
  const w = 140;
  const h = 36;
  const populated = values.filter((v): v is number => v != null);
  if (populated.length < 2) {
    return <div className="h-9 text-xs text-[var(--ua-navy)]/40">no data</div>;
  }
  // Span the sparkline across each series' own populated range so series with
  // null edges (water temp, streamflow) draw the same horizontal extent as
  // series that span all points (air temp).
  const firstIdx = values.findIndex((v) => v != null);
  let lastIdx = -1;
  for (let i = values.length - 1; i >= 0; i--) {
    if (values[i] != null) {
      lastIdx = i;
      break;
    }
  }
  const idxSpan = lastIdx - firstIdx || 1;
  const min = Math.min(...populated);
  const max = Math.max(...populated);
  const span = max - min || 1;
  // Build segments, breaking on internal nulls so gaps stay visible.
  const segments: string[] = [];
  let buf: string[] = [];
  for (let i = firstIdx; i <= lastIdx; i++) {
    const v = values[i];
    if (v == null) {
      if (buf.length) {
        segments.push(`M${buf.join(" L")}`);
        buf = [];
      }
      continue;
    }
    const x = ((i - firstIdx) / idxSpan) * (w - 4) + 2;
    const y = h - 2 - ((v - min) / span) * (h - 4);
    buf.push(`${x.toFixed(1)},${y.toFixed(1)}`);
  }
  if (buf.length) segments.push(`M${buf.join(" L")}`);
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="h-9 w-full" role="img">
      {segments.map((d, i) => (
        <path key={i} d={d} fill="none" stroke={color} strokeWidth={1.5} />
      ))}
    </svg>
  );
}

export function InputsPanel({ points }: Props) {
  const series: Series[] = [
    {
      label: "Air temp (max)",
      unit: "°C",
      values: points.map((p) => p.air_temp_c_max),
    },
    {
      label: "Water temp",
      unit: "°C",
      values: points.map((p) => p.water_temp_c),
    },
    {
      label: "Streamflow",
      unit: "kcfs",
      values: points.map((p) =>
        p.streamflow_cfs == null ? null : p.streamflow_cfs / 1000,
      ),
    },
  ];
  return (
    <div className="flex flex-col gap-3">
      {series.map((s) => {
        const last = [...s.values].reverse().find((v) => v != null) ?? null;
        return (
          <div key={s.label} className="flex flex-col gap-1">
            <div className="flex items-baseline justify-between text-xs">
              <span className="text-[var(--ua-navy)]/70">{s.label}</span>
              <span className="font-mono text-[var(--ua-navy)]">
                {fmtNumber(last, 1)} {s.unit}
              </span>
            </div>
            <Sparkline
              values={s.values}
              // Air = red (heat signal), Water + Streamflow = navy (river system).
              color={s.label.startsWith("Air") ? "#AB0520" : "#0C234B"}
            />
          </div>
        );
      })}
    </div>
  );
}
