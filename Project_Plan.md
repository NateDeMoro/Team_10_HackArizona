# Nuclear Cooling-Water Derating Forecaster — Project Plan

## Context

This project forecasts nuclear plant cooling-water derating risk 1–14 days ahead using public weather and water data. v1 targets a single reactor (Quad Cities Unit 1, Mississippi River, Constellation/Cordova IL); the UI is built so additional reactors can be slotted in later. The judging company is nuclear-adjacent, so the project is positioned at a real, expensive, weather-driven operational problem (TVA Browns Ferry-class events cost $50M+ per summer; industry-wide $200M+) where no public forecaster exists today.

The repo currently contains only the initial commit (`README.md`, `.env` with the Open-Meteo paid API key). Local tooling (`uv`, `pnpm`, `just`) is installed. The plan follows six tiers; each tier produces something demoable so we can stop at any point and still ship something honest.

## Open-Meteo paid-tier note (changes Tier 4)

The customer endpoints exposed by the paid plan include `customer-historical-forecast-api.open-meteo.com`, which serves **archived NWP forecast runs** (not just ERA5 reanalysis). This eliminates the largest credibility caveat in v1 of the plan: Tier 4 backtests can use the actual forecast that would have been available on a given historical date, instead of hindsight reanalysis. The Tier 4 deliverables below have been adjusted accordingly.

API key lives in `.env` at repo root and is read as `OPENMETEO_API_KEY`. Required base URLs:
- Forecast: `https://customer-api.open-meteo.com/v1/forecast`
- Historical Archive (ERA5 actuals): `https://customer-archive-api.open-meteo.com/v1/archive`
- Historical Forecast (archived NWP runs): `https://customer-historical-forecast-api.open-meteo.com/v1/forecast`
- Geocoding: `https://customer-geocoding-api.open-meteo.com/v1/search`
- Ensemble: `https://customer-ensemble-api.open-meteo.com/v1/ensemble`

Authentication is via `?apikey=...` query parameter (lowercase, one word) on every request.

## Repo Structure (created in Tier 0)

```
repo/
├── api/                          # FastAPI backend
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py               # FastAPI app, route registration
│   │   ├── routes/
│   │   │   ├── plants.py         # GET /plants, GET /plants/{id}
│   │   │   ├── forecast.py       # GET /plants/{id}/forecast
│   │   │   └── backtest.py       # GET /plants/{id}/backtest?as_of=YYYY-MM-DD
│   │   ├── schemas.py            # Pydantic request/response models (copied from ml/)
│   │   ├── model_loader.py       # Loads XGBoost artifact at startup
│   │   └── data_loader.py        # Reads Parquet from /data
│   ├── pyproject.toml            # uv-managed
│   ├── Dockerfile
│   └── railway.toml
├── ml/                           # Offline pipeline
│   ├── pipeline/
│   │   ├── __init__.py
│   │   ├── ingest_nrc.py         # NRC power status scraper + parser
│   │   ├── ingest_eia.py         # EIA-860 plant metadata
│   │   ├── ingest_weather.py     # Open-Meteo archive + historical-forecast
│   │   ├── ingest_usgs.py        # USGS water temp + streamflow, with 05420500/05420400 stitch
│   │   ├── features.py           # Wet-bulb, heat index, lags, rolling windows
│   │   ├── build_dataset.py      # Joins everything into training Parquet
│   │   ├── train.py              # XGBoost training, 4 horizons
│   │   ├── baselines.py          # Climatology, persistence, refueling-aware climatology
│   │   ├── backtest.py           # "As-if-standing-on" historical evaluation
│   │   └── inference.py          # Forecast for a given run date (live or historical)
│   ├── notebooks/                # EDA scratch (not committed beyond Tier 1 sanity plot)
│   ├── schemas.py                # Shared with api/ — feature names, plant id enum
│   ├── pyproject.toml            # uv-managed
│   └── justfile                  # Pipeline targets: ingest, features, train, backtest
├── web/                          # Next.js frontend
│   ├── app/
│   │   ├── layout.tsx
│   │   ├── page.tsx              # US map landing
│   │   └── plants/[id]/page.tsx  # Plant detail with forecast + replay
│   ├── components/
│   │   ├── PlantMap.tsx          # Leaflet
│   │   ├── ForecastChart.tsx     # Recharts
│   │   ├── ReplaySlider.tsx
│   │   └── FeatureAttributions.tsx
│   ├── lib/
│   │   └── api.ts                # Typed fetch wrappers
│   ├── package.json              # pnpm
│   ├── Dockerfile
│   └── railway.toml
├── data/                         # gitignored, populated by ml/
│   ├── raw/                      # Cached source pulls
│   ├── interim/                  # Per-source tidy Parquet
│   ├── processed/                # Final training dataset
│   └── artifacts/                # model_h{1,3,7,14}.json, metrics.json
├── justfile                      # Top-level targets: dev-api, dev-web, train, backtest
├── .env                          # gitignored, OPENMETEO_API_KEY=...
├── .env.example                  # committed template
├── .gitignore
├── README.md
└── Project_Plan.md
```

`ml/schemas.py` is the canonical contract. A copy is placed in `api/app/schemas.py` at build time (decision: copy, not local-path dependency, for hackathon simplicity). The `api/` container does not pull in `ml/` — it's heavy and not needed at serving time.

Railway layout: one project, two services (`api` and `web`).

---

## Tier 0 — Scaffold

**Deliverables**
- Repo structure above, all directories present.
- `api/`: FastAPI app with `GET /healthz` returning `{"status":"ok"}`, Dockerfile, Railway config.
- `web/`: Next.js App Router app with a placeholder landing page that pings `/healthz` via the API base URL env var.
- `ml/`: empty pipeline modules with function stubs and a `just no-op` target that runs end-to-end and prints "ok".
- Top-level `justfile` with `dev-api`, `dev-web`, `train`, `backtest`, `lint` targets.
- `.gitignore` covering `data/`, `node_modules/`, `.venv/`, `__pycache__/`, `.next/`, `.env*` (with `!.env.example` exception).
- `.env.example` committed with `OPENMETEO_API_KEY=` placeholder.
- Both services deployed to Railway behind their respective subdomains; web reaches api via private networking.

**Acceptance criteria**
- `just dev-api` and `just dev-web` both run locally without errors.
- Visiting the local web app shows "API: ok" sourced from the live FastAPI healthcheck.
- Both Railway deploys are green; web deploy can hit api healthcheck.
- A no-op `ml` pipeline run completes without raising.

**Risks / mitigations**
- *Railway private networking misconfiguration.* Get the `/healthz` round-trip green in Railway before any data work begins.
- *uv vs pnpm friction in CI.* Skip CI in Tier 0 — only Railway build matters for now.
- *Custom domain setup.* Defer until Tier 5; Railway-provided subdomains are fine for development.

**Decisions resolved**
- Railway: one project with two services.
- Shared schema strategy: copy `schemas.py` into `api/` at Docker build.

**Dependencies:** none.

---

## Tier 1 — Labels

**Deliverables**
- `ml/pipeline/ingest_nrc.py`: downloads NRC power status files for 1999–current, caches raw text in `data/raw/nrc/`, parses the pipe-delimited format, normalizes dates to UTC daily, writes `data/interim/nrc_power_status.parquet` (all units) and `data/interim/labels_quad_cities_1.parquet` (filtered).
- A one-off Tier 1 sanity plot (matplotlib PNG committed under `ml/notebooks/figures/qc1_power_history.png`) showing the full Quad Cities 1 capacity-factor timeseries.
- `just ingest-labels` justfile target.

**Acceptance criteria**
- Labels file covers ≥99% of expected calendar days from 1999-01-01 to yesterday for Quad Cities 1 (gaps recorded as null, never imputed).
- Sanity plot visibly shows refueling outages (clusters of 0% spanning ~2–4 weeks) and at least one historically documented summer dip (e.g., 2012 Midwest heatwave).
- Re-running ingestion is idempotent and uses the on-disk cache (no re-download for already-fetched years; current year always re-fetches).

**Risks / mitigations**
- *NRC schema drift across years.* Parser must be tolerant — log and skip malformed rows rather than crash; assert ≥95% parse rate per year.
- *Refueling outages contaminating training.* Don't filter at this tier; create a boolean `is_outage` flag (e.g., 14+ consecutive days at 0%) and store it alongside the label. Filtering decision lives in Tier 3.
- *Unit-name disambiguation.* NRC files identify reactors by name string; lock the canonical "Quad Cities 1" string in `schemas.py` and assert it's present in every annual file.

**Decisions needed before starting**
- How to treat extended outage periods in labels: drop entirely from training, or mask with `is_outage` and let the model learn to ignore them? (Recommend mask — gives more data and is honest at inference.)

**Dependencies:** Tier 0 scaffold.

---

## Tier 2 — Features

**Deliverables**
- `ml/pipeline/ingest_weather.py`: pulls Open-Meteo customer-archive at (41.7261, -90.3097) hourly for `temperature_2m`, `dew_point_2m`, `relative_humidity_2m`, `wind_speed_10m`, `shortwave_radiation`, `precipitation`, `surface_pressure`. Caches per-year Parquet under `data/raw/weather/`. Aggregates to daily (min/mean/max for temp; mean for the rest; sum for precip). Writes `data/interim/weather_quad_cities.parquet`.
- `ml/pipeline/ingest_usgs.py`: pulls USGS daily values for 05420500 (1999–2021) and 05420400 (2021–present), stitches them with an explicit overlap-period sanity check, writes `data/interim/water_quad_cities.parquet`.
- `ml/pipeline/ingest_eia.py`: downloads EIA-860 nuclear plant table once, writes `data/interim/eia_nuclear_plants.parquet` (used by the UI in Tier 5; only Quad Cities is consumed by ML).
- `ml/pipeline/features.py`: wet-bulb (Stull 2011), heat index, 1/3/7/14-day lags of weather + water vars, 7/14/30-day rolling means and maxes, day-of-year sinusoidal encodings.
- `ml/pipeline/build_dataset.py`: left-joins features to labels on date, writes `data/processed/training_dataset.parquet`.
- `just features` justfile target chaining the three ingest scripts + build_dataset.

**Acceptance criteria**
- Training Parquet has one row per calendar day, no duplicates, UTC dates throughout.
- Wet-bulb computation validated against 3+ hand-checked rows from a published table.
- USGS stitch: overlap period (if any exists between sites) compared and the correlation logged; if no overlap, a clear comment in the code documents the discontinuity.
- Coverage report printed at end of `just features`: % non-null per column, per year — air temp should be ~100%, water temp will have gaps, especially winter.

**Risks / mitigations**
- *Open-Meteo paid-plan rate limits.* Cache aggressively per (location, year); never re-pull a year already cached. Use the `apikey` query parameter on every request.
- *USGS water temp seasonal sensor downtime.* Many USGS gauges remove temp sensors over winter. Don't impute; leave null and let XGBoost handle missingness natively.
- *Timezone bugs.* Single normalization point at ingestion (UTC). Add an assertion in `build_dataset.py` that every date column is tz-naive UTC dates.
- *Leakage via rolling windows.* Rolling features must be computed with `closed="left"` semantics so a row's features only see strictly-prior data.

**Decisions needed before starting**
- USGS stitch: treat 05420500 and 05420400 as the same series, or carry a `gauge_id` feature? (Recommend treat as same — they're <30mi apart on the same river; document the seam.)
- Daily aggregation window: calendar UTC day, or local-solar day? (Recommend UTC for code simplicity; the seasonal signal swamps the few-hour offset.)

**Dependencies:** Tier 1 (labels file).

---

## Tier 3 — Baseline Model

**Deliverables**
- `ml/pipeline/baselines.py`: implements three baselines — climatology (day-of-year mean from train period), persistence (yesterday's value), refueling-aware climatology (climatology conditioned on `is_outage` flag from Tier 1).
- `ml/pipeline/train.py`: trains four XGBoost regressors (horizons 1, 3, 7, 14), time-based splits (train 1999–2018, val 2019–2021, test 2022–present), optional sample-weighting to down-weight outage rows, saves `data/artifacts/model_h{1,3,7,14}.json`.
- `data/artifacts/metrics.json`: MAE and RMSE per horizon for model + each baseline, on val and test.
- `data/artifacts/shap_summary_h7.png`: SHAP summary plot for the 7-day horizon model.
- `just train` justfile target.

**Acceptance criteria**
- Model beats all three baselines on test MAE at every horizon.
- Test MAE for the 7-day horizon is at minimum better than persistence by ≥10% (sanity bar, not a target).
- SHAP plot shows air temperature, water temperature, and their lags/rolling stats among the top 5 features (physics sanity check). If they aren't, stop and investigate before continuing — a leak or a feature bug is the most likely cause.
- `metrics.json` is human-readable and gets pasted into the README.

**Risks / mitigations**
- *Class imbalance — derating events are rare.* This is a regression problem so it's blunted, but consider sample-weighting summer months or using quantile loss. Defer quantile loss unless time permits; report MAE conditional on summer-only test rows in `metrics.json` for honesty.
- *In-sample test scores will look great and mislead us.* This is exactly why Tier 4 backtest exists — keep Tier 3 metrics framed as "in-sample test" and never put them on the demo slide alone.
- *Confidence bands.* For Tier 3, generate quick bands via XGBoost quantile regression at q=0.1/0.5/0.9 OR via residual bootstrapping on val. Pick whichever is faster to wire — bands are required by Tier 5.

**Decisions needed before starting**
- Treatment of outage rows in training: drop, sample-weight to ~0, or pass `is_outage` as a feature. (Recommend pass as feature; the model will learn to predict ~0 when it's true. At inference we'll always pass `is_outage=False`, so the model effectively predicts "weather-driven capacity factor.")
- Confidence-band approach: quantile regression vs bootstrap. (Recommend quantile regression — single training run gives all three quantiles per horizon.)

**Dependencies:** Tier 2 (training dataset).

---

## Tier 4 — Inference and Backtest

**Updated by paid Open-Meteo plan:** the historical-forecast endpoint serves archived NWP forecast runs, so backtests can use what was actually forecast on a given run date — not ERA5 hindsight. This is the version of Tier 4 we should build.

**Deliverables**
- `ml/pipeline/inference.py`: function `forecast(plant_id, run_date) -> ForecastResponse`. Behavior:
  - For `run_date == today`: pull `customer-api.open-meteo.com/v1/forecast` (live forecast).
  - For historical `run_date`: pull `customer-historical-forecast-api.open-meteo.com/v1/forecast` (archived NWP forecast as of that date).
  - Returns predicted capacity factor + p10/p90 bands at h=1, 3, 7, 14.
- `ml/pipeline/backtest.py`: runs `forecast(...)` standing on each of N historical run dates, compares to the realized power status over the following 14 days, writes `data/artifacts/backtest_results.parquet` and a `backtest_report.md`.
- `api/app/routes/forecast.py`: `GET /plants/{id}/forecast` returns a precomputed forecast JSON (regenerated by a manual `just forecast` job for the demo).
- `api/app/routes/backtest.py`: `GET /plants/{id}/backtest?as_of=YYYY-MM-DD` reads from precomputed Parquet.
- Backtest covers at minimum: 2012-07-15 (Midwest heatwave), 2018-07-01, 2021-08-01, 2022-07-15, 2023-08-15.

**Acceptance criteria**
- Backtest report includes a horizon-vs-MAE chart on the chosen historical dates and is materially worse than in-sample test MAE — that's the honest signal we want.
- For at least one historical heatwave, the model's "as-if-standing-on" 7-day forecast directionally calls a derating dip even if it under/overshoots magnitude.
- API endpoints return validated Pydantic responses; both work locally and on Railway.

**Risks / mitigations**
- *Historical-forecast API coverage.* Open-Meteo's archived NWP runs may not extend back to 1999. If 2012-07-15 isn't covered, fall back to ERA5 reanalysis for that single date with a clear caveat in the report; keep the post-coverage backtest dates honest.
- *Water temp not available for forecast horizon.* At inference we only have water observations up to today. Treat future water temps as model-imputed (a small sub-model: water temp at t+k regressed on current water temp + air temp forecast at t+k). Recommend the sub-model — a few hours' work and improves long-horizon skill.
- *Forecast precomputation cadence.* For the demo, run `just forecast` manually before showtime. Don't burn Tier 4 time on a scheduler.

**Decisions needed before starting**
- Set of historical backtest dates: keep the five above, or expand? (Recommend the five — covers diverse summers without blowing scope.)
- Future-water-temp strategy: sub-model vs lag-only. (Recommend sub-model.)

**Dependencies:** Tier 3 (model artifacts), Tier 2 (feature pipeline reused for inference-time feature construction).

---

## Tier 5 — Web App

**Deliverables**
- `web/app/page.tsx`: US map (Leaflet) showing all nuclear plants from EIA-860; Quad Cities is the only "live" marker (filled and colored by current 7-day forecast risk); rest are placeholder markers (greyed out, click → "Model coming soon").
- `web/app/plants/[id]/page.tsx`: detail page with
  - Forecast chart (Recharts): historical actuals (last 30 days) + 14-day forecast curve with p10/p90 bands.
  - Weather inputs panel: small sparklines for air temp, water temp, streamflow over the forecast window.
  - SHAP feature attributions: top 5 features driving the current prediction (bar chart).
  - Replay slider: scrub by day across the full backtest period; updates the chart to show what the model predicted on that historical date alongside what actually happened.
- `web/lib/api.ts`: typed fetch wrappers for `/plants`, `/plants/{id}/forecast`, `/plants/{id}/backtest`.
- Both services deployed to Railway behind a custom domain.
- README with screenshots and a one-paragraph "what's honest, what isn't" disclaimer.

**Acceptance criteria**
- Demo can be driven on a phone or laptop without a local dev environment.
- Replay slider feels responsive (<300ms per scrub) — this requires precomputing all backtest forecasts at deploy time.
- Lighthouse perf score ≥80 on the plant detail page (mostly a check that we didn't ship something embarrassingly heavy).
- Disclaimer paragraph is visible on the landing page footer.

**Risks / mitigations**
- *Backtest replay too slow if computed on demand.* Precompute every (plant, date) backtest forecast offline, write to Parquet, serve as static JSON via the API. Slider just hits cached endpoints.
- *Map performance with all ~90 US reactors.* Marker clustering not needed at that count; a plain Leaflet `LayerGroup` is fine.
- *Custom domain DNS propagation.* Buy/configure the domain at the start of Tier 5 so propagation isn't blocking demo morning.
- *Mobile responsiveness.* shadcn/ui defaults are responsive; spot-check on one phone and call it done.

**Decisions needed before starting**
- Replay slider granularity: scrub by day, week, or both? (Recommend day-only — simplest.)
- Domain name: pick before Tier 5 starts. (We need at least 24h for DNS.)
- Color scale for the map: discrete risk tiers (green/yellow/red) or continuous gradient? (Recommend three tiers — easier to read at a glance.)
- Whether to list all ~90 US reactors as placeholders or only the ~30 PJM/MISO ones to keep the map less cluttered. (Recommend all — sells the "scaling is the next step" story.)

**Dependencies:** Tier 4 (precomputed forecasts and backtests).

---

## Tier 6 — Stretch (pick one only if Tier 5 is solid)

Listed in recommended order:

1. **Operator dollar-value layer.** Multiplies predicted MW lost by historical PJM AEP-Dayton hub LMP (PJM publishes free historical LMP via Data Miner 2). Outputs an expected-loss confidence interval per forecast. The single most compelling addition for a nuclear-judging panel because it converts forecast skill into dollars.
2. **Add Quad Cities Unit 2.** Tests whether the model trained on Unit 1 generalizes to a colocated unit — important credibility check; minimal new pipeline code.
3. **Cooper or Prairie Island as a second real plant.** Validates cross-site transfer; requires another USGS gauge mapping and a re-train.
4. **Gemma 4 operator briefings via Gemini API.** Wire a `/plants/{id}/briefing` endpoint that takes the 14-day forecast + SHAP top features and produces a 3-sentence operator-style summary. Block: needs the API key.

**Decision needed:** which stretch to pursue. Recommendation depends on remaining time after Tier 5 — if ≥4 hours left, do #1; if 1–2 hours, do #2.

---

## Cross-cutting concerns

- **Commit cadence.** Commit at the end of every working pipeline step. A working ugly artifact beats a polished broken one.
- **Data caching.** Every ingest script writes to `data/raw/<source>/` and never re-fetches existing files unless the user passes `--refresh`. Same convention across all three ingest scripts.
- **Logging.** Use Python `logging` at INFO; one log line per file written, with row counts and date range.
- **Testing.** No unit tests at the hackathon scale. Each tier's "acceptance criteria" is the test.
- **Secrets.** `OPENMETEO_API_KEY` lives in `.env`, gitignored. `.env.example` is committed as a template. If Gemini API key lands in Tier 6, follow the same pattern.

## Verification (end-to-end)

After all tiers (or any subset):
1. `just ingest-labels && just features && just train && just backtest` runs clean from a fresh checkout (modulo cached `data/raw/`).
2. `just dev-api` and `just dev-web` come up locally; web app renders the map, Quad Cities marker is colored, plant detail page renders forecast chart + SHAP attributions + replay slider.
3. Replay slider scrubbed to 2012-07-15 shows a visible derating dip in the model output and the realized actuals.
4. Same flow works on the Railway-deployed URL.
5. `data/artifacts/metrics.json` and `data/artifacts/backtest_report.md` are present and consistent with what's shown in the UI.

## Concerns and pushback worth flagging

- **Refueling outages dominate the label timeseries.** Roughly 30 days every 18–24 months at 0%. The Tier 3 plan recommends passing `is_outage` as a feature so the model still trains on those dates while learning to predict ~0 when the flag is on; at inference we always pass false and predict the "weather-driven" capacity factor.
- **Quad Cities thermal-discharge derating may be rare in the historical record.** Quad Cities has once-through cooling on a large river; it's not the most-derated plant in the country. The model will mostly learn "summer = slightly lower." If the demo would benefit from showing dramatic dips, Tier 6 #3 (Cooper or Prairie Island) is the path; Browns Ferry would put us in TVA's lane and the project explicitly avoids that. Worth a conversation before Tier 6.
- **EIA-860 is annual.** Fine for plant metadata but won't reflect mid-year retirements (e.g., Palisades 2022). Note this in the README.
- **Open-Meteo at the plant lat/lon is a single point.** Cooling water comes from upstream; air temp at the intake matters more than at the reactor footprint. For Quad Cities the difference is negligible (river is right there) but for inland-cooling-pond plants this would need a watershed-aware approach. Out of scope for v1; flag for future work.
- **Historical-forecast API coverage horizon.** The biggest unknown for Tier 4. If Open-Meteo's archived NWP runs only go back ~5–10 years, the older backtest dates (2012, 2018) may need to fall back to ERA5 reanalysis — which reintroduces the hindsight caveat for those specific dates. Mitigation: explicitly label each backtest row with the forecast source used.
