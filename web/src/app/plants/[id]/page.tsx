import Link from "next/link";
import { notFound } from "next/navigation";

import { AlertBadge } from "@/components/AlertBadge";
import { AttributionBars } from "@/components/AttributionBars";
import { ForecastChart } from "@/components/ForecastChart";
import { InputsPanel } from "@/components/InputsPanel";
import { ReplaySlider } from "@/components/ReplaySlider";
import {
  getActuals,
  getAttributions,
  getBacktestDates,
  getForecast,
  getInputs,
  getPlant,
  type ActualsResponse,
  type AttributionsResponse,
  type BacktestDatesResponse,
  type ForecastResponse,
  type InputsResponse,
  type Plant,
} from "@/lib/api";
import { fmtDate } from "@/lib/format";

export const dynamic = "force-dynamic";

type Params = Promise<{ id: string }>;

type DetailData = {
  plant: Plant;
  forecast: ForecastResponse | null;
  actuals: ActualsResponse | null;
  inputs: InputsResponse | null;
  attributions: AttributionsResponse | null;
  backtestDates: BacktestDatesResponse | null;
};

async function fetchDetail(id: string): Promise<DetailData> {
  const plant = await getPlant(id);
  if (!plant.modeled) {
    return {
      plant,
      forecast: null,
      actuals: null,
      inputs: null,
      attributions: null,
      backtestDates: null,
    };
  }
  // Fetch all five datasets in parallel; tolerate individual failures so
  // the page still renders the parts that loaded.
  const [forecast, actuals, inputs, attributions, backtestDates] = await Promise.all([
    getForecast(id).catch(() => null),
    getActuals(id, 30).catch(() => null),
    getInputs(id, 30).catch(() => null),
    getAttributions(id).catch(() => null),
    getBacktestDates(id).catch(() => null),
  ]);
  return { plant, forecast, actuals, inputs, attributions, backtestDates };
}

export default async function PlantDetail({ params }: { params: Params }) {
  const { id } = await params;
  let data: DetailData;
  try {
    data = await fetchDetail(id);
  } catch {
    notFound();
  }
  const { plant, forecast, actuals, inputs, attributions, backtestDates } = data;

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
          className="text-xs text-[var(--ua-navy)]/60 hover:text-[var(--ua-red)]"
        >
          ← back to catalog
        </Link>
        <header className="flex flex-col gap-1 border-l-4 border-[var(--ua-red)] pl-4">
          <h1 className="text-2xl font-semibold tracking-tight text-[var(--ua-navy)]">
            {plant.display_name}
          </h1>
          <p className="text-sm text-[var(--ua-navy)]/60">{meta}</p>
        </header>
        <div className="rounded-xl border border-dashed border-[var(--ua-navy)]/30 bg-[var(--ua-navy)]/[0.03] p-6 text-sm text-[var(--ua-navy)]/80">
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
        className="text-xs text-[var(--ua-navy)]/60 hover:text-[var(--ua-red)]"
      >
        ← back to catalog
      </Link>

      <header className="flex flex-wrap items-start justify-between gap-3 border-l-4 border-[var(--ua-red)] pl-4">
        <div className="flex flex-col gap-1">
          <h1 className="text-2xl font-semibold tracking-tight text-[var(--ua-navy)]">
            {plant.display_name}
          </h1>
          <p className="text-sm text-[var(--ua-navy)]/60">{meta}</p>
        </div>
        {headlineHorizon ? (
          <div className="flex flex-col items-end gap-1">
            <AlertBadge level={headlineHorizon.alert_level} />
            <span className="text-xs text-[var(--ua-navy)]/60">
              7-day point: {headlineHorizon.point_pct.toFixed(1)}%
            </span>
          </div>
        ) : null}
      </header>

      <section className="grid grid-cols-1 gap-6 lg:grid-cols-4">
        <div className="rounded-xl border border-[var(--ua-navy)]/15 bg-white p-4 shadow-sm lg:col-span-3">
          <div className="mb-3 flex items-baseline justify-between">
            <h2 className="text-sm font-semibold text-[var(--ua-navy)]">
              14-day forecast
            </h2>
            {forecast ? (
              <span className="text-xs text-[var(--ua-navy)]/60">
                Run {fmtDate(forecast.run_date)} · source {forecast.source}
              </span>
            ) : null}
          </div>
          {forecast && actuals ? (
            <ForecastChart
              actuals={actuals.points}
              forecast={forecast.horizons}
              runDate={forecast.run_date}
            />
          ) : (
            <NoData label="forecast cache" />
          )}
        </div>
        <aside className="rounded-xl border border-[var(--ua-navy)]/15 bg-white p-4 shadow-sm">
          <h2 className="mb-3 text-sm font-semibold text-[var(--ua-navy)]">
            Recent inputs
          </h2>
          {inputs ? (
            <InputsPanel points={inputs.points} />
          ) : (
            <NoData label="weather/water cache" />
          )}
        </aside>
      </section>

      <section className="rounded-xl border border-[var(--ua-navy)]/15 bg-white p-4 shadow-sm">
        <div className="mb-3 flex items-baseline justify-between">
          <h2 className="text-sm font-semibold text-[var(--ua-navy)]">
            Top features driving the 7-day forecast
          </h2>
          <span className="text-xs text-[var(--ua-navy)]/60">
            SHAP, capacity-factor pp
          </span>
        </div>
        {headlineAttribution ? (
          <AttributionBars
            features={headlineAttribution.top_features}
            baselinePct={headlineAttribution.baseline_pct}
            pointPct={headlineAttribution.point_pct}
          />
        ) : (
          <NoData label="attributions cache" />
        )}
      </section>

      <section className="rounded-xl border border-[var(--ua-navy)]/15 bg-white p-4 shadow-sm">
        <div className="mb-3 flex items-baseline justify-between">
          <h2 className="text-sm font-semibold text-[var(--ua-navy)]">
            Replay backtest
          </h2>
          <span className="text-xs text-[var(--ua-navy)]/60">
            Predicted-vs-realized at every horizon, anchored at a chosen
            run date
          </span>
        </div>
        {backtestDates && backtestDates.dates.length > 0 ? (
          <ReplaySlider
            plantId={plant.id}
            dates={backtestDates.dates}
            highlights={backtestDates.highlights}
          />
        ) : (
          <NoData label="backtest cache" />
        )}
      </section>

      <footer className="border-t-2 border-[var(--ua-red)]/30 pt-6 text-xs text-[var(--ua-navy)]/70">
        Symmetric uncertainty band is the per-horizon 80th-percentile of
        absolute validation residuals (target ~80% empirical coverage).
        Forecast curves above 95% mean the model expects no weather-driven
        derating; values below 90% trigger the red alert tier. Refueling
        outage and pre-outage days are excluded from the actuals series to
        avoid burying the weather signal under operations.
      </footer>
    </main>
  );
}

function NoData({ label }: { label: string }) {
  return (
    <div className="rounded-md bg-[var(--ua-navy)]/[0.03] p-4 text-xs text-[var(--ua-navy)]/70">
      Missing {label}. Run <code className="font-mono">just forecast</code> /{" "}
      <code className="font-mono">just backtest</code> on the operator&apos;s
      machine to refresh the artifacts the API serves.
    </div>
  );
}
