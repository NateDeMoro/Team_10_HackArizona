// Typed client for the Derating Forecast API. Mirrors api/app/schemas.py;
// keep field names in sync when the Pydantic models change.

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

// --- Shared enums ----------------------------------------------------------

export type ForecastSource = "live" | "historical_nwp" | "era5_fallback";
export type AlertLevel = "operational" | "watch" | "alert";

// --- Plants ---------------------------------------------------------------

export type Plant = {
  id: string;
  display_name: string;
  operator: string | null;
  river: string | null;
  lat: number;
  lon: number;
  state: string | null;
  plant_code: number | null;
  nameplate_mw: number | null;
  modeled: boolean;
};

// --- Forecast --------------------------------------------------------------

export type HorizonPrediction = {
  horizon_days: number;
  target_date: string; // ISO date
  point_pct: number;
  band_low_pct: number;
  band_high_pct: number;
  alert_level: AlertLevel;
};

export type ForecastResponse = {
  plant_id: string;
  run_date: string;
  source: ForecastSource;
  horizons: HorizonPrediction[];
};

// --- Actuals --------------------------------------------------------------

export type ActualPoint = {
  date: string;
  power_pct: number | null;
  is_outage: boolean;
};

export type ActualsResponse = {
  plant_id: string;
  days: number;
  points: ActualPoint[];
};

// --- Inputs (sparklines) --------------------------------------------------

export type WeatherInputPoint = {
  date: string;
  air_temp_c_max: number | null;
  water_temp_c: number | null;
  streamflow_cfs: number | null;
};

export type InputsResponse = {
  plant_id: string;
  points: WeatherInputPoint[];
};

// --- Attributions (SHAP) --------------------------------------------------

export type FeatureContribution = {
  feature: string;
  value: number | null;
  contribution_pct: number;
};

export type HorizonAttribution = {
  horizon_days: number;
  baseline_pct: number;
  point_pct: number;
  top_features: FeatureContribution[];
};

export type AttributionsResponse = {
  plant_id: string;
  run_date: string;
  horizons: HorizonAttribution[];
};

// --- Briefing (LLM-generated daily summary) -------------------------------

export type BriefingRiskDay = {
  target_date: string;
  horizon_days: number;
  point_pct: number;
  alert_level: AlertLevel;
  explanation: string;
};

export type BriefingResponse = {
  plant_id: string;
  run_date: string;
  generated_at: string; // ISO datetime
  model_id: string;
  headline: string;
  risk_days: BriefingRiskDay[];
  drivers: string[];
  outlook: string;
  fallback: boolean;
};

// --- Backtest --------------------------------------------------------------

export type BacktestRow = {
  horizon_days: number;
  run_date: string;
  target_date: string;
  actual_pct: number | null;
  point_pct: number;
  band_low_pct: number;
  band_high_pct: number;
};

export type BacktestResponse = {
  plant_id: string;
  as_of: string;
  source: ForecastSource;
  rows: BacktestRow[];
};

export type BacktestDatesResponse = {
  plant_id: string;
  dates: string[];
  highlights: string[];
};

export type BacktestSeriesPoint = {
  date: string;
  actual_pct: number | null;
  point_pct: number;
};

export type BacktestSeriesResponse = {
  plant_id: string;
  horizon_days: number;
  points: BacktestSeriesPoint[];
};

// --- History (calendar month) ---------------------------------------------

export type DipCategory =
  | "operational"
  | "weather_dependent"
  | "non_weather_dependent"
  | "refueling"
  | "post_refuel_recovery";

export type HistoryPoint = {
  date: string;
  power_pct: number;
  is_outage: boolean;
  prediction_pct: number | null;
  dip_category: DipCategory;
};

export type HistoryResponse = {
  plant_id: string;
  year: number;
  points: HistoryPoint[];
};

// --- Health ---------------------------------------------------------------

export type Health = { status: string };

// --- Fetcher --------------------------------------------------------------

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!res.ok) {
    let detail = "";
    try {
      const body = await res.json();
      detail = typeof body?.detail === "string" ? `: ${body.detail}` : "";
    } catch {
      // body wasn't JSON; ignore
    }
    throw new Error(`${path} ${res.status}${detail}`);
  }
  return res.json() as Promise<T>;
}

// --- Endpoint wrappers ----------------------------------------------------

export const getHealth = () => getJson<Health>("/healthz");

export const listPlants = () => getJson<Plant[]>("/plants");

export const getPlant = (plantId: string) =>
  getJson<Plant>(`/plants/${encodeURIComponent(plantId)}`);

export const getForecast = (plantId: string) =>
  getJson<ForecastResponse>(`/plants/${encodeURIComponent(plantId)}/forecast`);

export const getActuals = (plantId: string, days = 30) =>
  getJson<ActualsResponse>(
    `/plants/${encodeURIComponent(plantId)}/actuals?days=${days}`,
  );

export const getInputs = (plantId: string, days = 30) =>
  getJson<InputsResponse>(
    `/plants/${encodeURIComponent(plantId)}/inputs?days=${days}`,
  );

export const getAttributions = (plantId: string) =>
  getJson<AttributionsResponse>(
    `/plants/${encodeURIComponent(plantId)}/attributions`,
  );

export const getBriefing = (plantId: string) =>
  getJson<BriefingResponse>(
    `/plants/${encodeURIComponent(plantId)}/briefing`,
  );

export const getBacktestDates = (plantId: string) =>
  getJson<BacktestDatesResponse>(
    `/plants/${encodeURIComponent(plantId)}/backtest/dates`,
  );

export const getBacktest = (plantId: string, asOf: string) =>
  getJson<BacktestResponse>(
    `/plants/${encodeURIComponent(plantId)}/backtest?as_of=${asOf}`,
  );

export const getHistoryYear = (plantId: string, year: number) =>
  getJson<HistoryResponse>(
    `/plants/${encodeURIComponent(plantId)}/history?year=${year}`,
  );

export const getBacktestSeries = (
  plantId: string,
  horizon: number,
  days: number,
) =>
  getJson<BacktestSeriesResponse>(
    `/plants/${encodeURIComponent(plantId)}/backtest/series?horizon=${horizon}&days=${days}`,
  );
