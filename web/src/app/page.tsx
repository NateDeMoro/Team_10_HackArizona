import Link from "next/link";

import { AlertBadge } from "@/components/AlertBadge";
import PlantMap from "@/components/PlantMapClient";
import {
  getForecast,
  listPlants,
  type AlertLevel,
  type Plant,
} from "@/lib/api";
import { ALERT_HEX, fmtDate } from "@/lib/format";

export const dynamic = "force-dynamic";

type Catalog = {
  plants: Plant[];
  qcLevel: AlertLevel | null;
  qcRunDate: string | null;
  qcPointPct: number | null;
};

async function fetchCatalog(): Promise<Catalog> {
  const plants = await listPlants();
  let qcLevel: AlertLevel | null = null;
  let qcRunDate: string | null = null;
  let qcPointPct: number | null = null;
  try {
    const fc = await getForecast("quad_cities_1");
    const h7 = fc.horizons.find((h) => h.horizon_days === 7) ?? fc.horizons[0];
    qcLevel = h7?.alert_level ?? null;
    qcRunDate = fc.run_date;
    qcPointPct = h7?.point_pct ?? null;
  } catch {
    // leave nulls
  }
  return { plants, qcLevel, qcRunDate, qcPointPct };
}

export default async function Home() {
  const { plants, qcLevel, qcRunDate, qcPointPct } = await fetchCatalog();
  const modeled = plants.filter((p) => p.modeled);

  return (
    <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-8 px-6 py-10">
      <header className="flex flex-col gap-2 border-l-4 border-[var(--ua-red)] pl-4">
        <h1 className="text-3xl font-semibold tracking-tight text-[var(--ua-navy)]">
          Nuclear Cooling-Water Derating Forecaster
        </h1>
        <p className="max-w-3xl text-sm text-[var(--ua-navy)]/75">
          Forecasts weather-driven cooling-water derating risk 1–14 days
          ahead for US nuclear reactors. v1 ships a single fully-modeled
          site (Quad Cities Unit 1, Mississippi River); the rest of the
          catalog is shown on the map as placeholders to communicate
          scaling.
        </p>
      </header>

      <section className="flex flex-col gap-3">
        <div className="flex items-baseline justify-between">
          <h2 className="text-lg font-semibold text-[var(--ua-navy)]">
            US fleet
          </h2>
          {qcRunDate ? (
            <span className="text-xs text-[var(--ua-navy)]/60">
              Forecast run: {fmtDate(qcRunDate)}
            </span>
          ) : null}
        </div>
        <PlantMap
          plants={plants}
          qcAlertLevel={qcLevel}
          qcPointPct={qcPointPct}
        />
        <Legend qcLevel={qcLevel} />
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold text-[var(--ua-navy)]">
          Modeled plants
        </h2>
        <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {modeled.map((p) => (
            <li key={p.id}>
              <Link
                href={`/plants/${p.id}`}
                className="group block rounded-xl border border-[var(--ua-navy)]/15 bg-white p-4 shadow-sm transition hover:border-[var(--ua-red)] hover:shadow-md"
              >
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <p className="text-sm font-semibold text-[var(--ua-navy)] group-hover:text-[var(--ua-red)]">
                      {p.display_name}
                    </p>
                    <p className="text-xs text-[var(--ua-navy)]/60">
                      {[p.operator, p.river, p.state]
                        .filter(Boolean)
                        .join(" · ")}
                    </p>
                  </div>
                  {qcLevel ? <AlertBadge level={qcLevel} /> : null}
                </div>
                <p className="mt-3 text-xs text-[var(--ua-navy)]/60">
                  7-day point forecast ·{" "}
                  <span className="font-mono text-[var(--ua-navy)]">
                    {qcPointPct == null
                      ? "no forecast cached"
                      : `${qcPointPct.toFixed(1)}%`}
                  </span>
                </p>
              </Link>
            </li>
          ))}
        </ul>
      </section>

      <footer className="mt-auto border-t-2 border-[var(--ua-red)]/30 pt-6 text-xs text-[var(--ua-navy)]/70">
        <strong className="text-[var(--ua-navy)]">
          What&apos;s honest, what isn&apos;t:
        </strong>{" "}
        Forecasts come from public weather (Open-Meteo) and water (USGS)
        data and a gradient-boosted regression trained on NRC daily power
        status. The model targets weather-driven derating only — refueling
        outages and pre-outage coastdown days are excluded from training.
        Backtests on 2023+ are honest, but are not a substitute for an
        operator&apos;s own thermal-discharge analysis.
      </footer>
    </main>
  );
}

function Legend({ qcLevel }: { qcLevel: AlertLevel | null }) {
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
      {qcLevel ? (
        <span className="ml-auto text-[var(--ua-navy)]/70">
          Quad Cities Unit 1:{" "}
          <span className="font-medium capitalize text-[var(--ua-navy)]">
            {qcLevel}
          </span>
        </span>
      ) : null}
    </div>
  );
}
