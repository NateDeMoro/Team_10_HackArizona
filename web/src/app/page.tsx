import Link from "next/link";

import { AlertBadge } from "@/components/AlertBadge";
import PlantMap from "@/components/PlantMapClient";
import {
  getForecast,
  listPlants,
  type AlertLevel,
  type Plant,
} from "@/lib/api";
import { ALERT_CARD_BG, ALERT_HEX, fmtDate } from "@/lib/format";

export const dynamic = "force-dynamic";

// Per-plant 14-day worst-case headline derived from each modeled plant's
// forecast. Shared between the map (badge color), the cards, and the
// legend. `pointPct` is the lowest point estimate across all horizons,
// and `level` is that horizon's tier.
export type ForecastSummary = {
  level: AlertLevel;
  runDate: string;
  pointPct: number;
};

type Catalog = {
  plants: Plant[];
  // plant_id -> headline; absent when the forecast endpoint failed.
  summaries: Record<string, ForecastSummary>;
};

async function fetchCatalog(): Promise<Catalog> {
  const plants = await listPlants();
  const modeled = plants.filter((p) => p.modeled);
  // Fetch every modeled plant's forecast in parallel; tolerate per-plant
  // failures so one missing artifact doesn't blank the whole map.
  const entries = await Promise.all(
    modeled.map(async (p): Promise<[string, ForecastSummary] | null> => {
      try {
        const fc = await getForecast(p.id);
        if (fc.horizons.length === 0) return null;
        const worst = fc.horizons.reduce((lo, h) =>
          h.point_pct < lo.point_pct ? h : lo,
        );
        return [
          p.id,
          {
            level: worst.alert_level,
            runDate: fc.run_date,
            pointPct: worst.point_pct,
          },
        ];
      } catch {
        return null;
      }
    }),
  );
  const summaries: Record<string, ForecastSummary> = {};
  for (const e of entries) if (e) summaries[e[0]] = e[1];
  return { plants, summaries };
}

export default async function Home() {
  const { plants, summaries } = await fetchCatalog();
  const modeled = plants.filter((p) => p.modeled);
  // Use the latest run_date across modeled plants for the header label.
  // All plants share the same ERA5 archive, so they should match — pick
  // any non-null one rather than picking arbitrarily.
  const headerRunDate =
    modeled
      .map((p) => summaries[p.id]?.runDate)
      .find((d): d is string => Boolean(d)) ?? null;

  return (
    <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-8 px-6 py-10">
      <header className="flex flex-col gap-2 border-l-4 border-[var(--ua-red)] pl-4">
        <h1 className="text-3xl font-semibold tracking-tight text-[var(--ua-navy)]">
          Nuclear Cooling-Water Derating Forecaster
        </h1>
        <p className="max-w-3xl text-sm text-[var(--ua-navy)]/75">
          Forecasts weather-driven cooling-water derating risk 1–14 days
          ahead for US nuclear reactors. v1 ships two fully-modeled sites
          (Quad Cities Unit 1 on the Mississippi and Byron Unit 1 on the
          Rock River); the rest of the catalog is shown on the map as
          placeholders to communicate scaling.
        </p>
      </header>

      <section className="flex flex-col gap-3">
        <div className="flex items-baseline justify-between">
          <h2 className="text-lg font-semibold text-[var(--ua-navy)]">
            US fleet
          </h2>
          {headerRunDate ? (
            <span className="text-xs text-[var(--ua-navy)]/60">
              Forecast run: {fmtDate(headerRunDate)}
            </span>
          ) : null}
        </div>
        <PlantMap plants={plants} summaries={summaries} />
        <Legend />
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold text-[var(--ua-navy)]">
          Modeled plants
        </h2>
        <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {modeled.map((p) => {
            const summary = summaries[p.id];
            const tint = summary
              ? ALERT_CARD_BG[summary.level]
              : "bg-white border-[var(--ua-navy)]/15 hover:border-[var(--ua-red)]";
            return (
            <li key={p.id}>
              <Link
                href={`/plants/${p.id}`}
                className={`group block rounded-xl border p-4 shadow-sm transition hover:shadow-md ${tint}`}
              >
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <p className="text-sm font-bold text-[var(--ua-navy)] group-hover:text-[var(--ua-red)]">
                      {p.display_name}
                    </p>
                    <p className="text-xs font-medium text-[var(--ua-navy)]">
                      {[p.operator, p.river, p.state]
                        .filter(Boolean)
                        .join(" · ")}
                    </p>
                  </div>
                  {summary ? <AlertBadge level={summary.level} /> : null}
                </div>
                <p className="mt-3 text-xs font-semibold text-[var(--ua-navy)]">
                  14-day forecast low point ·{" "}
                  <span className="font-mono font-bold text-[var(--ua-navy)]">
                    {summary == null
                      ? "no forecast cached"
                      : `${summary.pointPct.toFixed(1)}%`}
                  </span>
                </p>
              </Link>
            </li>
            );
          })}
        </ul>
      </section>

    </main>
  );
}

function Legend() {
  return (
    <div className="flex flex-wrap items-center gap-4 text-xs text-[var(--ua-navy)]/70">
      <span className="font-medium text-[var(--ua-navy)]">Map legend:</span>
      {(["operational", "watch", "alert"] as const).map((lv) => (
        <span key={lv} className="flex items-center gap-1.5 capitalize">
          <span
            className="inline-block h-3 w-3 rounded-full ring-1 ring-black/5"
            style={{ background: ALERT_HEX[lv] }}
          />
          {lv}
        </span>
      ))}
      <span className="flex items-center gap-1.5">
        <span className="inline-block h-3 w-3 rounded-full bg-zinc-400/40 ring-1 ring-zinc-400" />
        placeholder (model coming soon)
      </span>
    </div>
  );
}
