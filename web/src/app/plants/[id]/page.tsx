import Link from "next/link";
import { notFound } from "next/navigation";

import { AlertBadge } from "@/components/AlertBadge";
import { AttributionBars } from "@/components/AttributionBars";
import { BriefingCard } from "@/components/BriefingCard";
import { ForecastView } from "@/components/ForecastView";
import { HistoryView } from "@/components/HistoryView";
import { InputsPanel } from "@/components/InputsPanel";
import {
  getAttributions,
  getBriefing,
  getForecast,
  getInputs,
  getPlant,
  type AttributionsResponse,
  type BriefingResponse,
  type ForecastResponse,
  type InputsResponse,
  type Plant,
} from "@/lib/api";
import { fmtDate } from "@/lib/format";
import { cn } from "@/lib/utils";

export const dynamic = "force-dynamic";

type Params = Promise<{ id: string }>;
type SearchParams = Promise<{ view?: string }>;

type View = "forecast" | "history";

function parseView(raw: string | undefined): View {
  return raw === "history" ? "history" : "forecast";
}

type DetailData = {
  plant: Plant;
  forecast: ForecastResponse | null;
  inputs: InputsResponse | null;
  attributions: AttributionsResponse | null;
  briefing: BriefingResponse | null;
};

async function fetchDetail(id: string): Promise<DetailData> {
  const plant = await getPlant(id);
  if (!plant.modeled) {
    return {
      plant,
      forecast: null,
      inputs: null,
      attributions: null,
      briefing: null,
    };
  }
  // Fetch the static datasets in parallel; tolerate individual failures
  // so the page still renders the parts that loaded. The History view
  // owns its own actuals/backtest fetches because they vary with window.
  const [forecast, inputs, attributions, briefing] = await Promise.all([
    getForecast(id).catch(() => null),
    getInputs(id, 30).catch(() => null),
    getAttributions(id).catch(() => null),
    getBriefing(id).catch(() => null),
  ]);
  return { plant, forecast, inputs, attributions, briefing };
}

export default async function PlantDetail({
  params,
  searchParams,
}: {
  params: Params;
  searchParams: SearchParams;
}) {
  const { id } = await params;
  const { view: rawView } = await searchParams;
  const view = parseView(rawView);

  let data: DetailData;
  try {
    data = await fetchDetail(id);
  } catch {
    notFound();
  }
  const { plant, forecast, inputs, attributions, briefing } = data;

  const headlineHorizon =
    forecast?.horizons.find((h) => h.horizon_days === 7) ?? forecast?.horizons[0];
  const headlineAttribution =
    attributions?.horizons.find((h) => h.horizon_days === 7) ??
    attributions?.horizons[0];

  const meta = [plant.operator, plant.river, plant.state]
    .filter(Boolean)
    .join(" · ");

  if (!plant.modeled) {
    return (
      <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-6 px-6 py-10">
        <Link
          href="/"
          className="text-xs text-[var(--ua-navy)]/85 hover:text-[var(--ua-red)]"
        >
          ← back to catalog
        </Link>
        <header className="flex flex-col gap-1 border-l-4 border-[var(--ua-red)] pl-4">
          <h1 className="text-2xl font-semibold tracking-tight text-[var(--ua-navy)]">
            {plant.display_name}
          </h1>
          <p className="text-sm text-[var(--ua-navy)]/85">{meta}</p>
        </header>
        <div className="rounded-xl border border-dashed border-[var(--ua-navy)]/40 bg-[var(--ua-navy)]/[0.05] p-6 text-sm text-[var(--ua-navy)]">
          Model coming soon. v1 only serves predictions for Quad Cities Unit 1;
          this plant is shown as a catalog placeholder so the map reflects
          the full US fleet.
        </div>
      </main>
    );
  }

  return (
    <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-8 px-6 py-10">
      <Link
        href="/"
        className="text-xs text-[var(--ua-navy)]/85 hover:text-[var(--ua-red)]"
      >
        ← back to catalog
      </Link>

      <header className="flex flex-wrap items-start justify-between gap-3 border-l-4 border-[var(--ua-red)] pl-4">
        <div className="flex flex-col gap-1">
          <h1 className="text-2xl font-semibold tracking-tight text-[var(--ua-navy)]">
            {plant.display_name}
          </h1>
          <p className="text-sm text-[var(--ua-navy)]/85">{meta}</p>
        </div>
        {headlineHorizon ? (
          <div className="flex flex-col items-end gap-1">
            <AlertBadge level={headlineHorizon.alert_level} />
            <span className="text-xs text-[var(--ua-navy)]/85">
              7-day point: {headlineHorizon.point_pct.toFixed(1)}%
            </span>
          </div>
        ) : null}
      </header>

      <section className="grid grid-cols-1 gap-6 lg:grid-cols-4">
        <div className="flex min-w-0 flex-col gap-6 lg:col-span-3">
          <div className="min-w-0 rounded-xl border border-[var(--ua-navy)]/25 bg-[#dbe8f7] p-4 shadow-sm">
            <div className="mb-3 flex items-baseline justify-between gap-3">
              <ViewToggle plantId={plant.id} active={view} />
              {forecast ? (
                <span className="text-xs text-[var(--ua-navy)]/85">
                  Run {fmtDate(forecast.run_date)} · source {forecast.source}
                </span>
              ) : null}
            </div>
            {view === "forecast" ? (
              forecast ? (
                <ForecastView
                  forecast={forecast.horizons}
                  runDate={forecast.run_date}
                />
              ) : (
                <NoData label="forecast cache" />
              )
            ) : (
              <HistoryView plantId={plant.id} />
            )}
          </div>

          <div className="grid min-w-0 grid-cols-1 gap-6 md:grid-cols-3">
            <div className="min-w-0 rounded-xl border border-[var(--ua-navy)]/25 bg-[#dbe8f7] p-4 shadow-sm md:col-span-2">
              <div className="mb-3 flex items-baseline justify-between gap-2">
                <h2 className="text-sm font-semibold text-[var(--ua-navy)]">
                  Top features driving the 7-day forecast
                </h2>
                <span className="text-xs text-[var(--ua-navy)]/85">
                  SHAP, capacity-factor pp
                </span>
              </div>
              {headlineAttribution ? (
                <AttributionBars
                  features={headlineAttribution.top_features}
                  baselinePct={headlineAttribution.baseline_pct}
                  pointPct={headlineAttribution.point_pct}
                  compact
                />
              ) : (
                <NoData label="attributions cache" />
              )}
            </div>

            <div className="min-w-0 rounded-xl border border-[var(--ua-navy)]/25 bg-[#dbe8f7] p-4 shadow-sm">
              <div className="mb-3 flex flex-col gap-0.5">
                <h2 className="text-sm font-semibold text-[var(--ua-navy)]">
                  Weather inputs feeding the 14-day forecast
                </h2>
                <span className="text-[11px] text-[var(--ua-navy)]/85">
                  Trailing 30-day conditions the model uses to project the
                  next 14 days
                </span>
              </div>
              {inputs ? (
                <InputsPanel points={inputs.points} />
              ) : (
                <NoData label="weather/water cache" />
              )}
            </div>
          </div>
        </div>

        <aside className="lg:self-start">
          {briefing ? <BriefingCard briefing={briefing} /> : null}
        </aside>
      </section>

      <footer className="border-t-2 border-[var(--ua-red)]/30 pt-6 text-xs text-[var(--ua-navy)]">
        Forecast curves above 95% mean the model expects no weather-driven
        derating and are clamped to 100% on the chart; values below 90%
        trigger the red alert tier. Refueling outage and pre-outage days
        are excluded from the actuals series to avoid burying the weather
        signal under operations.
      </footer>
    </main>
  );
}

function ViewToggle({ plantId, active }: { plantId: string; active: View }) {
  const items: { view: View; label: string }[] = [
    { view: "forecast", label: "Forecast" },
    { view: "history", label: "History" },
  ];
  return (
    <div className="inline-flex overflow-hidden rounded-md border border-[var(--ua-navy)]/20 text-sm">
      {items.map(({ view, label }) => {
        const href = `/plants/${plantId}${view === "forecast" ? "" : "?view=history"}`;
        const isActive = view === active;
        return (
          <Link
            key={view}
            href={href}
            className={cn(
              "px-3 py-1.5 font-medium transition",
              isActive
                ? "bg-[var(--ua-navy)] text-white"
                : "bg-white text-[var(--ua-navy)] hover:bg-[var(--ua-navy)]/[0.05]",
            )}
          >
            {label}
          </Link>
        );
      })}
    </div>
  );
}

function NoData({ label }: { label: string }) {
  return (
    <div className="rounded-md bg-[var(--ua-navy)]/[0.05] p-4 text-xs text-[var(--ua-navy)]">
      Missing {label}. Run <code className="font-mono">just forecast</code> /{" "}
      <code className="font-mono">just backtest</code> on the operator&apos;s
      machine to refresh the artifacts the API serves.
    </div>
  );
}
