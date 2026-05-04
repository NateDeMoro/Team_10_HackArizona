# Architecture — Nuclear Cooling-Water Derating Forecaster

Three Railway services (`ml`, `api`, `web`) plus a Postgres addon. The `ml`
service writes artifacts into Postgres on a daily cron; the `api` reads
them; the `web` renders them. No service shares a filesystem with another
at runtime — Postgres is the only data plane between them.

## High-level

```
                 ┌─────────────────────────── External data sources ───────────────────────────┐
                 │                                                                              │
                 │   Open-Meteo paid API           USGS NWIS                NRC daily power     │
                 │   ─ archive (ERA5)              ─ water temp 00010      status (pipe-       │
                 │   ─ historical-forecast NWP     ─ discharge   00060      delimited)         │
                 │   ─ forecast (live)             (per-plant gauges)       EIA-860 nuclear    │
                 │                                                          plant table        │
                 └──────────────────────────────────────────────────────────────────────────────┘
                                                       │
                                                       │  HTTPS pulls (cached per-plant/year
                                                       │  in ml/data/raw/, idempotent re-runs)
                                                       ▼
┌──────────────────────────────────────────────────────────────────────────────────────────────┐
│  ml/  service  (Railway cron, daily)              entrypoint:  python -m pipeline.refresh   │
│                                                                                              │
│   plants.py  ── single source of truth for slug → (lat/lon, NRC unit, USGS sites)           │
│                                                                                              │
│   pipeline.refresh ─┐                                                                        │
│                     │  for slug in PLANTS:                                                   │
│                     ├──▶ ingest_weather  ─ Open-Meteo  ─▶ ml/data/raw/weather/<slug>/        │
│                     ├──▶ ingest_usgs     ─ USGS NWIS   ─▶ ml/data/raw/usgs/                  │
│                     ├──▶ features        (Stull wet-bulb, lags, rolling, DOY sinusoidal)     │
│                     ├──▶ build_dataset                  ─▶ ml/data/processed/<slug>/         │
│                     ├──▶ inference (loads model_h{1..14}_point.json + calibrator_h{H}.json) │
│                     │      └─▶ forecast_latest.json + attributions_latest.json               │
│                     ├──▶ backtest      (replay 2023+ test split, dip-focused report)         │
│                     │      └─▶ backtest_results.parquet + backtest_metrics.json              │
│                     └──▶ briefing      (Bedrock / Gemma-class LLM, best-effort)              │
│                            └─▶ briefing_latest.json                                          │
│                                                                                              │
│   Offline-only (run by hand, NOT on the cron):                                              │
│      ingest_nrc → labels_<slug>.parquet                                                      │
│      ingest_eia → eia_nuclear_plants.parquet  (uploaded once with plant_id=_global)          │
│      train      → model_h{H}_point.json, calibrator_h{H}.json, band_deltas.json,            │
│                   feature_columns.json, metrics.json, shap_summary_h7.png                    │
│                                                                                              │
│   Upload step (end of refresh.py):                                                           │
│      psycopg → UPSERT INTO forecast_artifacts (plant_id, artifact_type, payload, refreshed) │
│                                                                                              │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
                                                       │
                                                       │  BYTEA blobs keyed by
                                                       │  (plant_id, artifact_type)
                                                       ▼
┌──────────────────────────────────────────────────────────────────────────────────────────────┐
│  Postgres (Railway addon)                                                                    │
│                                                                                              │
│    forecast_artifacts                                                                        │
│    ─────────────────                                                                         │
│    plant_id       TEXT     ← slug or "_global"                                               │
│    artifact_type  TEXT     ← forecast | attributions | briefing | backtest_metrics |        │
│                              backtest_results | labels | weather | water | eia_plants        │
│    payload        BYTEA    ← JSON utf-8 OR raw parquet bytes                                 │
│    refreshed_at   TZ       ← bumped by every UPSERT; the api watches MAX() for changes      │
│    PK (plant_id, artifact_type)                                                              │
│                                                                                              │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
                                                       │
                                                       │  psycopg SELECT payload …
                                                       │  (5-min in-memory TTL cache)
                                                       ▼
┌──────────────────────────────────────────────────────────────────────────────────────────────┐
│  api/  service  (Railway, FastAPI on uvicorn)         CMD: uvicorn app.main:app             │
│                                                                                              │
│   lifespan:  ── _prewarm()  pulls every artifact into byte cache at startup                  │
│              ── _watcher()  polls MAX(refreshed_at) every 60s; on change → clear+reprewarm  │
│                                                                                              │
│   db.py            psycopg connection + TTL byte-cache                                       │
│   data_loader.py   typed loaders: load_forecast / load_attributions / load_briefing /       │
│                    load_backtest_metrics / load_backtest_dates / load_recent_actuals /      │
│                    load_recent_inputs / load_eia_plants                                      │
│   model_loader.py  (held over from Tier 0 — api ships no XGBoost at serve time)             │
│   schemas.py       copied from ml/schemas.py at build (canonical Pydantic contract)          │
│                                                                                              │
│   routes/                          response                          source artifact         │
│   ─────────────────────────────────────────────────────────────────────────────────────     │
│   GET  /healthz                    {status: ok}                      —                       │
│   GET  /plants                     Plant[]                           eia_plants + registry  │
│   GET  /plants/{id}                Plant                              ↑                       │
│   GET  /plants/{id}/forecast       ForecastResponse                  forecast               │
│   GET  /plants/{id}/backtest       BacktestResponse (?as_of=…)       backtest_results       │
│   GET  /plants/{id}/actuals        recent labels (last N days)       labels                  │
│   GET  /plants/{id}/inputs         recent weather + water sparklines weather + water        │
│   GET  /plants/{id}/attributions   SHAP top-features for h=7         attributions           │
│   GET  /plants/{id}/briefing       3-sentence operator summary       briefing               │
│   GET  /plants/{id}/history        actuals overlaid on past preds    backtest_results+labels│
│                                                                                              │
│   CORS: GET-only, allow_origins=*                                                            │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
                                                       │
                                                       │  HTTPS JSON  (typed via lib/api.ts)
                                                       ▼
┌──────────────────────────────────────────────────────────────────────────────────────────────┐
│  web/  service  (Railway, Next.js App Router, pnpm)   CMD: next start                        │
│                                                                                              │
│   src/app/                                                                                   │
│     layout.tsx                       global shell                                             │
│     page.tsx                         US fleet map landing — fetches /plants and /forecast    │
│                                      for every modeled plant in parallel for badge color     │
│     plants/[id]/page.tsx             plant detail (forecast + history + inputs + briefing)   │
│                                                                                              │
│   src/components/                                                                            │
│     PlantMap.tsx / PlantMapClient.tsx   Leaflet map of all EIA-860 reactors                  │
│     ForecastView.tsx                    Recharts: 14-day point + symmetric residual band     │
│     HistoryView.tsx                     replay overlay (actuals vs past predictions)         │
│     InputsPanel.tsx                     air temp / water temp / streamflow sparklines        │
│     AttributionBars.tsx                 SHAP top-5 bars for h=7                              │
│     BriefingCard.tsx                    LLM-authored operator summary                        │
│     AlertBadge.tsx                      operational | watch | alert pill                     │
│                                                                                              │
│   src/lib/api.ts        typed fetch wrappers (matches Pydantic contract)                     │
│   src/lib/format.ts     ALERT_HEX color scale, fmtDate helpers                               │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
```

## Data flow at a glance

1. **Daily, on cron** — `ml.refresh` pulls fresh weather + water for every
   plant in `PLANTS`, rebuilds features, runs `inference` against
   pre-trained per-horizon XGBoost models with their isotonic
   calibrators, re-runs the dip-focused backtest, regenerates the
   LLM briefing, and UPSERTs every artifact into `forecast_artifacts`.
   `refreshed_at` advances on every row written.
2. **Within ~60s** — the `api` watcher notices `MAX(refreshed_at)` moved,
   clears the byte cache, and re-prewarms it from Postgres.
3. **On each request** — routes hit the typed loaders in
   `data_loader.py`, which return cached bytes (or pull-then-cache on
   miss) and validate against the `schemas.py` Pydantic contract.
4. **Render** — Next.js server components fetch through `lib/api.ts` and
   render the map / charts / briefing card.

## Key contracts

- **Plant registry** — `ml/plants.py:PLANTS` is the only place a slug maps
  to coordinates and gauges. Adding a third plant is one entry plus
  re-running the offline `train` target; the cron will start refreshing
  it automatically on the next tick.
- **Pydantic schemas** — `ml/schemas.py` is canonical and copied to
  `api/app/schemas.py` at build time. `web/src/lib/api.ts` mirrors the
  same shapes by hand.
- **Artifact key** — `(plant_id, artifact_type)` in `forecast_artifacts`.
  `plant_id="_global"` is the sentinel for non-plant-scoped data
  (currently just `eia_plants`).
- **Model artifacts ship in the ml image, not Postgres** — only outputs
  flow through Postgres. Re-training requires a code deploy.

## What lives where (vs. the original Project_Plan)

- The plan described JSON/parquet on a shared `/data` volume; the
  shipped architecture replaced that with Postgres BYTEA blobs so the
  `api` and `ml` services can scale independently.
- Two plants are fully wired through the API and UI
  (`quad_cities_1`, `byron_1`); the `web` map shows every EIA-860
  reactor as a placeholder.
- The `briefing` service (Bedrock / Gemma-class LLM) was added as part
  of the Tier 6 stretch and is wired all the way through to a
  `BriefingCard` on the plant detail page.
