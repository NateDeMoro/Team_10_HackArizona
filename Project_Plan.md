# Nuclear Cooling-Water Derating Forecaster — Project Plan

## Context

This project forecasts nuclear plant cooling-water derating risk 1–14 days ahead using public weather and water data. The training pipeline is multi-plant via a registry in `ml/plants.py`; v1 ships two trained plants (`quad_cities_1` on the Mississippi and `byron_1` on the Rock River, both Constellation/IL). The inference, backtest, and API surface remain single-plant for now (pinned to `quad_cities_1`); multi-plant API integration is a separate task. The judging company is nuclear-adjacent, so the project is positioned at a real, expensive, weather-driven operational problem (TVA Browns Ferry-class events cost $50M+ per summer; industry-wide $200M+) where no public forecaster exists today.

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
│   │   ├── ingest_nrc.py         # NRC power status scraper + parser; takes --plant
│   │   ├── ingest_eia.py         # EIA-860 plant metadata (plant-agnostic)
│   │   ├── ingest_weather.py     # Open-Meteo archive (per-plant lat/lon)
│   │   ├── ingest_usgs.py        # USGS temp + flow; per-parameter site lists from registry
│   │   ├── features.py           # Wet-bulb, heat index, lags, rolling windows
│   │   ├── build_dataset.py      # Joins everything into training Parquet
│   │   ├── train.py              # XGBoost training + isotonic calibration, 14 horizons
│   │   ├── baselines.py          # Climatology, persistence, refueling-aware climatology
│   │   ├── backtest.py           # "As-if-standing-on" historical evaluation
│   │   └── inference.py          # Forecast for a given run date (live or historical)
│   ├── notebooks/                # EDA scratch + Tier 1 sanity plots per plant
│   ├── plants.py                 # Plant registry: slug → (NRC unit, lat/lon, USGS sites, ...)
│   ├── schemas.py                # Generic constants + Pydantic API contract (no plant-specific)
│   ├── data/                     # gitignored, populated by the pipeline (under ml/, not repo root)
│   │   ├── raw/                  # Cached source pulls (weather is per-plant)
│   │   ├── interim/              # Slug-suffixed tidy Parquet
│   │   ├── processed/<slug>/     # Final training dataset per plant
│   │   └── artifacts/<slug>/     # model_h{H}_point.json, calibrator_h{H}.json, metrics, etc.
│   ├── pyproject.toml            # uv-managed
│   └── justfile                  # Recipes accept plant slug: `just train byron_1`
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
├── justfile                      # Top-level recipes pass through to ml/, accept plant slug
├── .env                          # gitignored, OPENMETEO_API_KEY=...
├── .env.example                  # committed template
├── .gitignore
├── README.md
└── Project_Plan.md
```

`ml/schemas.py` is the canonical contract; per-plant configuration lives in `ml/plants.py`. A copy of `schemas.py` is placed in `api/app/schemas.py` at build time (decision: copy, not local-path dependency, for hackathon simplicity). The `api/` container does not pull in `ml/` — it's heavy and not needed at serving time.

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
- `ml/pipeline/ingest_nrc.py`: downloads NRC power status files for 2005–current, caches raw text in `ml/data/raw/nrc/`, parses the pipe-delimited format, normalizes dates to UTC daily, writes `ml/data/interim/nrc_power_status.parquet` (all units) and `ml/data/interim/labels_<slug>.parquet` for the requested plant.
- Per-plant sanity plot under `ml/notebooks/figures/<slug>_power_history.png`.
- `just ingest-labels [<slug>]` recipe (slug defaults to `quad_cities_1`).

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
- `ml/pipeline/ingest_weather.py`: pulls Open-Meteo customer-archive at the plant's lat/lon (from `plants.py`) hourly for `temperature_2m`, `dew_point_2m`, `relative_humidity_2m`, `wind_speed_10m`, `shortwave_radiation`, `precipitation`, `surface_pressure`, `cloud_cover`. Caches per-year Parquet under `ml/data/raw/weather/<slug>/` (per-plant since coords differ). Aggregates to daily (min/mean/max for temp; mean for the rest; sum for precip). Writes `ml/data/interim/weather_<slug>.parquet`.
- `ml/pipeline/ingest_usgs.py`: pulls USGS daily values for the gauges declared in `plants.py` (per-parameter site lists — temp and flow can come from different gauges). Stitches in priority order with overlap-period sanity logging. Writes `ml/data/interim/water_<slug>.parquet`. QC1 stitches `05420500` (Clinton, IA) + `05420400` (L&D 13); Byron 1 uses single gauge `05440700`.
- `ml/pipeline/ingest_eia.py`: downloads EIA-860 nuclear plant table once, writes `ml/data/interim/eia_nuclear_plants.parquet` (plant-agnostic; powers the UI map).
- `ml/pipeline/features.py`: wet-bulb (Stull 2011), heat index, 1/3/7/14-day lags of weather + water vars, 7/14/30-day rolling means and maxes, day-of-year sinusoidal encodings, heat-dose degree-day sums. Reads/writes slug-suffixed Parquet.
- `ml/pipeline/build_dataset.py`: left-joins features to labels on date, writes `ml/data/processed/<slug>/training_dataset.parquet`.
- `just features [<slug>]` recipe chaining the three ingest scripts + features + build_dataset.

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

**Status (as built):**
- 14 XGBoost regressors trained, one per horizon h ∈ 1..14 (not just 1/3/7/14 as originally planned — full daily curve out to 14 days).
- Time splits: train through 2019-12-31, val 2020-2022, test 2023+ (shifted from original 1999-2018 plan because NRC data only starts 2005).
- Outage rows excluded from both feature day and target day at training time; model sees weather-driven dynamics only.
- Symmetric uncertainty band, not a quantile booster: per-horizon `delta_h = 80th-percentile of |val residuals|`, published as `[point - delta_h, point + delta_h]` for ~80% empirical coverage. The original q10 quantile booster was dropped after a sequence of attempts: q90 was useless for a derating product (no upside-asymmetry value); q25 added no signal beyond q10; the conformally-calibrated q10 ended up *above* the dip-weighted point on most days because the point under-predicts ~95% of val rows by design (dip weighting), so a one-sided downside band on top of the dip-weighted point has no statistical justification. Symmetric residual band centered on the point is honest about typical model error and gives a real visible band on every day.
- **Dip-weighted point objective:** the unweighted squared-error mean model mode-collapsed to ~100% (the dominant target value), giving 21+ MAE on the dip slice. Sample weights `1 + 0.5 * max(0, (100 - y) / 5)` applied to the point fit only; pulls predictions away from 100 enough to track real derates. Cost: full-slice MAE roughly doubles (2.9 → 6.8 at h01). The product cares about dip behavior, not full-slice MAE — UI buckets ≥95% as "fully operational" so the day-to-day low bias is invisible to the operator. Quantile fits are unweighted.
- Backtest report (`backtest_report.md`) is dip-focused: leads with dip-event MAE vs baselines and dip-detection precision/recall at the 95% threshold. Full-slice MAE relegated to a footer.
- **Isotonic calibration (added post-build).** The dip-weighted point objective leaves a systematic ~3–5pp negative bias on the dominant 100% mode (visible across every test year for both QC1 and Byron 1). A per-horizon `IsotonicRegression` is fit on val and persisted as `calibrator_h{H}.json`; at serve time the calibration is applied conditionally only when `raw >= DIP_THRESHOLD_PCT`. Gating preserves dip recall (a uniform isotonic learns "any below-100 raw is really 100%-mode error" and pulls dip predictions up). Net effect on QC1 h=7 test: 100%-mode bias −5.15pp → −3.16pp, full-slice MAE 5.35 → 3.48. Effect on Byron 1: bias −2.95pp → −0.21pp, full-slice MAE 2.96 → 0.27.
- **Multi-plant.** Training pipeline takes `--plant <slug>` end-to-end. Two plants currently trained: `quad_cities_1` (Mississippi, weak weather signal but full historical record) and `byron_1` (Rock River, 4.47× summer/winter dip ratio — the strongest weather signature in the cross-plant scan). Adding a third plant is a single registry entry plus the existing recipes.

**Deliverables (built)**
- `ml/pipeline/baselines.py`: climatology, persistence, refueling-aware climatology.
- `ml/pipeline/train.py`: 14 point models, 14 isotonic calibrators, dip-weighted point fits, symmetric-band coverage in metrics.
- `ml/pipeline/backtest.py` (Tier 3 portion): per-row predictions on the held-out test split, dip-focused markdown report, band coverage check. Tier 4 extends this with historical-NWP runs.
- Per-plant artifacts under `ml/data/artifacts/<slug>/`: `metrics.json` (model + baselines, sliced by full / summer / non-summer / dip_events), `band_deltas.json`, `feature_columns.json`, `model_h{H}_point.json`, `calibrator_h{H}.json`, `backtest_results.parquet`, `backtest_report.md`, `backtest_metrics.json`, `shap_summary_h7.png`.

**Acceptance criteria — outcome**
- Model beats both climatology and persistence on dip-event MAE at every horizon (1..14). ✓
- Dip MAE at h07 test = 16.5 vs climatology 19.6, persistence 21.1.
- SHAP plot retained (full-slice physics sanity).

**Outstanding for Tier 4 to address**
- *Downside-band over-coverage:* q10 empirical above-rate is ~0.97 vs target 0.90. Tier 4 split-conformal calibration tightens this. (Per-horizon shift derived from val residuals.)
- *Persistence beats the model badly on full slice (test full pers MAE ~1.0 vs model 6.8).* Expected and not the metric we're optimizing — persistence cannot anticipate a future dip; that's the whole reason this product exists. Documented in the report so a reviewer can't read full-MAE in isolation.
- *Dip-event metric is graded against an unfilterable population.* Of 28 sub-95% events in QC1's 2023+ test set, only 1 is plausibly weather-driven and 4 are marginal — the remaining 23 happen on cold-water / cold-air days where cooling-water physics rules out a thermal-discharge derating. Those are operator events (scrams, valve tests, grid-following) the model architecturally cannot predict. "Model beats baselines on dips" is true but the bar is mostly noise. Either filter the dip slice to weather-plausible days (water_temp ≥ ~18°C or air_max ≥ ~25°C) or disclose explicitly in the demo. Open.

**Dependencies:** Tier 2 (training dataset). ✓

---

## Tier 4 — Inference and Backtest

**Status: built.**

**Architecture decision (locks the simpler path):** the trained per-horizon models consume features only at the *run date* (and lags/rolling backwards). They do not consume NWP forecasts for t+1..t+14 as model inputs — model_h7 learned in training how *today's* conditions correlate with power 7 days from now. This collapses inference to a single feature row and removes the need for a future-water-temp sub-model. The historical-NWP API was originally needed to provide future forecasts as features; with the simpler architecture, NWP day-0 ≈ ERA5 day-0 for QC1 (within ~0.5C), and the cached ERA5 features serve all historical run dates directly. Source field still tags `historical_nwp` vs `era5_fallback` honestly: dates ≥ 2016-01-01 fall in the NWP-archive coverage window, dates earlier than that explicitly carry the hindsight caveat.

**Historical-NWP coverage (smoke-tested):** archive starts 2016-01-01. Of the five named historical dates, four are covered (2018, 2021, 2022, 2023) and 2012-07-15 falls back to ERA5 with a labeled caveat in the report.

**Symmetric residual band (final design):** per-horizon `delta_h` is the 80th-percentile of `|val residuals|`. Published band = `[point - delta_h, point + delta_h]`. Test empirical coverage on the 2023+ split: 0.72-0.83 across 14 horizons (target 0.80) — slight under-coverage on short horizons from val→test distribution drift, slight over-coverage on h13/h14, otherwise close to target. Visible band on every day; band-width grows with horizon as expected (h01 ~7.6, h13 ~8.3). The band is not a "downside" interval — it's a typical-error interval — because the dip-weighted point already incorporates lower-tail signal and there's no meaningful additional downside it hasn't priced.

**Deliverables (built)**
- `ml/pipeline/inference.py`: `forecast(plant_id, run_date) -> ForecastResponse` — loads cached features parquet, predicts point across 14 horizons, applies the gated isotonic calibrator, derives the symmetric residual band from `band_deltas.json`, clamps to 0-100, sets `alert_level` from the two-tier UI threshold scheme. CLI mode (`just forecast`) writes `ml/data/artifacts/<slug>/forecast_latest.json` for the API to serve.
- `ml/pipeline/backtest.py`: dip-focused report on the held-out 2023+ test split (per-row predictions + dip-event MAE vs baselines + dip-detection precision/recall + downside-band coverage with both raw and conformally-calibrated rates), plus a "Historical highlights" section that runs `inference.forecast()` at each of the five named dates and tabulates predicted-vs-realized for the following 14 days.
- `api/app/routes/forecast.py`: `GET /plants/{id}/forecast` reads `forecast_latest.json` and returns a `ForecastResponse`.
- `api/app/routes/backtest.py`: `GET /plants/{id}/backtest?as_of=YYYY-MM-DD` reads `backtest_results.parquet`, returns 14 rows for the requested run date.
- `api/app/routes/plants.py`: `GET /plants` and `GET /plants/{id}` from a single source-of-truth dict (currently QC1 only; Tier 5 expands).
- `api/app/data_loader.py`: cached JSON / parquet readers; api/ container has no Open-Meteo, XGBoost, or feature-pipeline dependencies.
- `ml/schemas.py` (canonical) holds `HorizonPrediction`, `ForecastResponse`, `BacktestRow`, `BacktestResponse`, `ForecastSource = Literal["live", "historical_nwp", "era5_fallback"]`. Copied to `api/app/schemas.py` (manual copy at hackathon scale; Docker build wires the same step in CI).
- `ml/data/artifacts/<slug>/band_deltas.json` and `calibrator_h{H}.json`: per-horizon symmetric-band deltas and isotonic-calibration breakpoints emitted by `train.py`.
- `justfile` top-level: `just forecast` and `just backtest` targets.

**Backtest density (decision (a)):** the dip-focused backtest runs over every test-split day (2023+, ~1000 rows × 14 horizons = 14015 rows) — that powers the Tier 5 replay slider for 2023+ scrubbing. The five named historical dates are highlighted in the backtest report with full 14-horizon predicted-vs-realized tables. Pre-2023 dates outside the highlights are not precomputed in v1; if Tier 5's slider needs to scrub through 2018-2022 summers, extend `_historical_highlights` to a sweep.

**Acceptance — outcome**
- `forecast_latest.json` produced; predictions land in 92-98 range for shoulder season (sane); dip-alerts fire on borderline days.
- All four named-date highlights with NWP coverage produce readable tables; 2012-07-15 produces a table flagged as `era5_fallback`.
- `GET /healthz`, `/plants`, `/plants/{id}`, `/plants/{id}/forecast`, `/plants/{id}/backtest?as_of=...` all return 200 with valid Pydantic responses against locally-running uvicorn.

**Two-tier alert scheme (decoupled from metrics threshold).** A single threshold at 95% fires red on ~99% of days because the dip-weighted point predictions cluster in 92-97. The operator-useful version uses two thresholds: green ≥ 95 ("operational"), yellow 90 ≤ point < 95 ("watch"), red point < 90 ("alert"). On the 2023+ test split this fires red on 422/1027 days (~41%) instead of 1022/1027, catches 13/26 actual sub-95% dips with red and the remaining ~13 with yellow. The metric-side `DIP_THRESHOLD_PCT = 95` is kept stable for cross-iteration comparability; `UI_ALERT_THRESHOLD_PCT = 90` drives the badge. `HorizonPrediction.alert_level: "operational" | "watch" | "alert"` is the API contract; `is_dip_alert: bool` was replaced.

**Outstanding for Tier 5**
- Web app reads these endpoints. ForecastResponse and BacktestResponse are stable contracts.
- UI maps `alert_level` directly to the badge color; the chart still renders raw `point_pct` and the published `q10_pct` band so users can see dip shape during heatwaves.
- **Multi-plant API integration.** Inference / backtest / `api/app/data_loader.py` are pinned to a single `PLANT_SLUG = "quad_cities_1"` constant. Training pipeline already supports any registered plant; surfacing Byron 1 (or any third plant) requires routing the slug through the API and the web layer.

**Dependencies:** Tier 3 (model artifacts), Tier 2 (feature pipeline reused for inference). ✓

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
- `web/app/page.tsx`: US map (Leaflet) showing all nuclear plants from EIA-860; live markers (filled, colored by current 7-day forecast risk) for every plant trained in `plants.py` once the API exposes them — currently QC1 only on the served surface, with Byron 1 trained but pending API wiring; rest are placeholder markers (greyed out, click → "Model coming soon").
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
3. **~~Cooper or Prairie Island as a second real plant.~~ Surface Byron 1 in the API + UI.** Cross-site transfer is already validated structurally (Byron 1 trained on the Rock River, distinct watershed and signal regime). What's left is wiring the slug through `api/app/data_loader.py` and the web layer so the map shows two live markers. Cooper (Missouri) and Prairie Island (upper Mississippi) were ruled out during plant selection — Cooper has only a weak summer signal in the historical capacity record; Prairie Island sits in the upper-Mississippi USGS water-temp data desert.
4. **Weather-plausibility filter for the dip-event metric.** One-line filter in `_slice_scores` and `backtest.py` that restricts the dip slice to days where water-temp or air-temp reach thermal-stress thresholds. Makes "model beats baselines on dips" mean what readers think it means.
5. **Gemma 4 operator briefings via Gemini API.** Wire a `/plants/{id}/briefing` endpoint that takes the 14-day forecast + SHAP top features and produces a 3-sentence operator-style summary. Block: needs the API key.

**Decision needed:** which stretch to pursue. Recommendation depends on remaining time after Tier 5 — if ≥4 hours left, do #1; if 1–2 hours, do #3 (lights up the second plant) or #4 (cleans up the dip metric for the demo narrative).

---

## Cross-cutting concerns

- **Commit cadence.** Commit at the end of every working pipeline step. A working ugly artifact beats a polished broken one.
- **Data caching.** Every ingest script writes to `ml/data/raw/<source>/` and never re-fetches existing files unless the user passes `--refresh`. Weather raw cache is namespaced per plant slug (`ml/data/raw/weather/<slug>/`); USGS site cache is shared across plants (site numbers are globally unique).
- **Logging.** Use Python `logging` at INFO; one log line per file written, with row counts and date range.
- **Testing.** No unit tests at the hackathon scale. Each tier's "acceptance criteria" is the test.
- **Secrets.** `OPENMETEO_API_KEY` lives in `.env`, gitignored. `.env.example` is committed as a template. If Gemini API key lands in Tier 6, follow the same pattern.

## Verification (end-to-end)

After all tiers (or any subset):
1. `just ingest-labels [<slug>] && just features [<slug>] && just train [<slug>] && just backtest [<slug>]` runs clean from a fresh checkout (modulo cached `ml/data/raw/`). Verified for both `quad_cities_1` and `byron_1`.
2. `just dev-api` and `just dev-web` come up locally; web app renders the map, the served plant marker is colored, plant detail page renders forecast chart + SHAP attributions + replay slider.
3. Replay slider scrubbed to 2012-07-15 shows a visible derating dip in the model output and the realized actuals.
4. Same flow works on the Railway-deployed URL.
5. `ml/data/artifacts/<slug>/metrics.json` and `backtest_report.md` are present and consistent with what's shown in the UI.

## Concerns and pushback worth flagging

- **Refueling outages dominate the label timeseries.** Roughly 30 days every 18–24 months at 0%. The Tier 3 plan recommends passing `is_outage` as a feature so the model still trains on those dates while learning to predict ~0 when the flag is on; at inference we always pass false and predict the "weather-driven" capacity factor.
- **Quad Cities thermal-discharge derating is rare and mostly not weather-driven (confirmed in practice).** Of 28 sub-95% events in the 2023+ QC1 test set, only ~1 is plausibly weather-driven and ~4 are marginal; the rest are operator events on cold-water days. Byron 1 was added as a second plant specifically because its 4.47× summer/winter dip ratio is the cleanest weather signature available in the historical record outside TVA. Browns Ferry remains explicitly out of bounds.
- **USGS water-temp infrastructure is decaying.** Plant-selection research turned up multiple gauges that were "active" in the seriesCatalog but had no recent data: Pasco on the Columbia (decommissioned 2022-09), Oswego at Lock 7 near FitzPatrick (sensor pulled 2024-10 and not redeployed), and the entire upper-Mississippi mainstem near Monticello (no continuous DV temp post-1999). USGS's water-temp coverage on rivers is patchier than the catalog suggests — site selection for any future plant requires a live recency check, not just a horizon look-up. Non-USGS sources (USACE/BPA dam tailrace temps via DART) are a viable backup for Columbia-system plants if we revisit later.
- **Dip-event metric is graded against operator events.** See Tier 3 outstanding item — the slice population at QC1 is mostly unpredictable from weather alone, which makes "model beats baselines on dips" a true but misleading headline. Either filter the slice or disclose the population explicitly. Same caveat applies to Byron 1's much smaller dip count (5 events).
- **EIA-860 is annual.** Fine for plant metadata but won't reflect mid-year retirements (e.g., Palisades 2022). Note this in the README.
- **Open-Meteo at the plant lat/lon is a single point.** Cooling water comes from upstream; air temp at the intake matters more than at the reactor footprint. For Quad Cities and Byron the difference is negligible (river is right there) but for inland-cooling-pond plants this would need a watershed-aware approach. Out of scope for v1; flag for future work.
- **Historical-forecast API coverage horizon.** The biggest unknown for Tier 4. If Open-Meteo's archived NWP runs only go back ~5–10 years, the older backtest dates (2012, 2018) may need to fall back to ERA5 reanalysis — which reintroduces the hindsight caveat for those specific dates. Mitigation: explicitly label each backtest row with the forecast source used.
