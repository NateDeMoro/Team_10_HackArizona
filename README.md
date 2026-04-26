# Nuclear Cooling-Water Derating Forecaster

A 14-day forecast of weather-driven nuclear power loss. Built for HackArizona, Team 10.

When a heatwave pushes river or air temperatures past a plant's cooling-water limits, the plant is forced to throttle back — a phenomenon called *derating* — exactly when grid demand is highest. Industry-wide losses from weather-driven derating run at $200M+ per year, and there is no public forecast of when it is coming. This project predicts derating risk one to fourteen days ahead using only public data, so plant and grid operators can plan around it instead of reacting to it.

The repository contains an offline machine-learning pipeline, a FastAPI service that exposes the resulting forecast, and a Next.js dashboard that visualizes it.

## Repository Layout

| Path | Purpose |
|------|---------|
| `ml/` | Offline pipeline. Ingests labels, weather, and water data; builds features; trains per-horizon XGBoost models with isotonic calibration; produces forecasts and backtests. |
| `api/` | FastAPI service. Serves precomputed forecasts and backtests via REST endpoints. No ML dependencies in the runtime container. |
| `web/` | Next.js dashboard. Renders a US map of plants and a per-plant detail page with the 14-day forecast curve, uncertainty band, alert level, and a historical replay slider. |
| `justfile` | Top-level recipes that pass through to `ml/`. Run `just train byron_1` or similar to operate on a non-default plant. |
| `Project_Plan.md` | Tier-by-tier plan and decisions log. |
| `Problems_Encountered.md` | Substantive problems hit during the build and how each was resolved. |
| `Stretch_Goals.md` | Tier 6 ideas considered but not all shipped. |
| `slides.html` | Five-slide presentation deck. |
| `poster.html` | Print-ready technical poster. |

## How It Works

The training pipeline is multi-plant and driven by a registry in `ml/plants.py`. Each plant declares its NRC unit name, latitude and longitude, and per-parameter USGS gauge lists. Two plants are currently trained: `quad_cities_1` (Mississippi River) and `byron_1` (Rock River, Illinois).

For each plant the pipeline:

1. Pulls daily power-status records from the NRC archive (1999–present) and tags refueling outages.
2. Pulls hourly weather from Open-Meteo's customer archive and aggregates to daily statistics.
3. Pulls daily streamflow and water-temperature records from USGS, stitching multiple gauges where needed.
4. Builds a feature set including wet-bulb temperature, heat-dose degree-day sums, lagged and rolling-window aggregates, and seasonal encodings.
5. Trains 14 XGBoost regressors — one per forecast horizon — with a dip-weighted point objective so the model does not collapse onto the dominant 100% capacity mode.
6. Fits a per-horizon isotonic calibrator on validation data and applies it conditionally at inference to remove the residual bias on the 100% mode without harming dip recall.
7. Publishes a symmetric residual band (80th-percentile of validation residuals) so every prediction carries a visible uncertainty range.

At serve time the API loads the resulting JSON artifact and returns it through `GET /plants/{id}/forecast`. The web app maps each day's predicted output percentage and alert level (operational, watch, alert) to the chart and badge.

## Running Locally

Tooling required: `uv`, `pnpm`, `just`. An Open-Meteo paid-tier API key is required for the weather ingest; place it in a root-level `.env` as `OPENMETEO_API_KEY=...` (see `.env.example`).

```bash
# One-time data build for a plant
just ingest-labels quad_cities_1
just features      quad_cities_1
just train         quad_cities_1
just backtest      quad_cities_1
just forecast      quad_cities_1

# Local services
just dev-api   # FastAPI on :8000
just dev-web   # Next.js on :3000
```

The web app reads its API base URL from an env var; with both services running locally, the dashboard renders the trained plants live.

## Deployment

Both services deploy to Railway as a single project with two services (`api` and `web`). The web service reaches the API over Railway's private network. Each service has its own `Dockerfile` and `railway.toml` checked in.

## Data and Honesty Notes

- **Public data only.** Open-Meteo (weather), USGS (water), NRC (plant power status), EIA-860 (plant metadata).
- **Forecast source is tagged.** Each historical backtest row carries a `ForecastSource` value (`live`, `historical_nwp`, or `era5_fallback`) so the difference between a real archived forecast and a hindsight-reanalysis fallback is never hidden.
- **Dip events are rare and noisy.** At Quad Cities Unit 1 most sub-95% capacity days in the test set are operator events on cold days, not weather-driven thermal-discharge derates. Byron Unit 1 was added because its 4.47x summer/winter dip ratio gives a much cleaner weather signal. The backtest report calls this out explicitly rather than burying it.
- **Persistence beats the model on full-slice MAE.** It cannot anticipate a future dip, which is the entire reason this product exists. The report leads with dip-event MAE — where the model beats both climatology and persistence at every horizon — and treats full-slice MAE as a footer.

See `Problems_Encountered.md` for a fuller account of what went wrong along the way and how each issue was resolved.

## License

Hackathon project; no license declared. Treat as all-rights-reserved unless and until a license is added.
