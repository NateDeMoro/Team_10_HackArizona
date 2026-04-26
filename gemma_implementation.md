# Implementation Plan: LLM-Powered Forecast Report (Gemma 3 27B via Bedrock)

## Context

The plant detail page currently surfaces a 14-day forecast chart, SHAP attribution bars, weather sparklines, and a history calendar. All of it speaks to a reader who already understands capacity factors, SHAP, and what "derating" means. Stretch goal #5 in `Stretch_Goals.md` calls for a plain-English summary aimed at someone who does not. This plan adds a structured multi-section briefing — generated daily, surfaced as a card in the right column of each plant's detail page — that translates the forecast and its drivers into language a non-expert can act on.

Decisions confirmed:
- Provider: AWS Bedrock, model `google.gemma-3-27b-instruct-v1:0` (or the regional equivalent — verify before wiring).
- Auth: long-term Bedrock bearer token (`AWS_BEARER_TOKEN_BEDROCK`), not IAM access key / secret pair. Default region `us-east-1`.
- Format: structured multi-section report (headline, risk days, drivers, bottom line). Text only — no inline visuals.
- Cadence: precomputed during the existing daily ML refresh and uploaded to Postgres alongside other artifacts. The API serves cached bytes; it never calls Bedrock.

## Approach

Mirror the existing `forecast` / `attributions` artifact pipeline end-to-end. New artifact type `briefing` flows: ml refresher generates JSON via Bedrock → uploads to `forecast_artifacts` table → API exposes `GET /plants/{id}/briefing` → web renders `BriefingCard` in the right column of `/plants/[id]`.

## Implementation Steps

### 1. Schema — `ml/schemas.py`
Add to the API contract section, after `AttributionsResponse`:
```python
class BriefingRiskDay(BaseModel):
    target_date: date
    horizon_days: int = Field(..., ge=1, le=14)
    point_pct: float
    alert_level: AlertLevel
    explanation: str

class BriefingResponse(BaseModel):
    plant_id: str
    run_date: date
    generated_at: datetime
    model_id: str
    headline: str
    risk_days: list[BriefingRiskDay]
    drivers: list[str]
    outlook: str
    fallback: bool = False
```
Mirror copy in `api/app/schemas.py` is auto-generated.

### 2. Bedrock client — `ml/pipeline/llm.py` (new)
Single public function:
```python
def invoke_bedrock_json(*, system: str, user: str, model_id: str,
                       region: str, max_tokens: int = 1500,
                       timeout_s: float = 30.0) -> dict
```
Uses `boto3` `bedrock-runtime` Converse API with long-term bearer-token auth. Reads `AWS_BEARER_TOKEN_BEDROCK`, `AWS_REGION` (default `us-east-1`), and `BEDROCK_MODEL_ID` from env — no `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`. boto3 picks up `AWS_BEARER_TOKEN_BEDROCK` natively for the `bedrock-runtime` service when present, so the client constructor stays a plain `boto3.client("bedrock-runtime", region_name=region)`. Requires `boto3>=1.39` (the version that introduced bearer-token support for Bedrock); pin in `ml/pyproject.toml`. Single retry on throttling/5xx; otherwise raises `BriefingError`. The `api` service does not depend on `boto3`.

### 3. Briefing generator — `ml/pipeline/briefing.py` (new)
Public surface mirrors `inference.py`:
```python
def briefing(plant_slug: str, run_date: date) -> BriefingResponse
def run(plant_slug: str) -> None    # CLI entry; writes briefing_latest.json
```
`briefing()` builds a compact context dict from:
- `data/artifacts/<slug>/forecast_latest.json` (just-written by inference)
- `data/artifacts/<slug>/attributions_latest.json` (top-5 SHAP per horizon, with raw values)
- Last 14 days of `data/interim/weather_<slug>.parquet` and `water_<slug>.parquet`
- `get_plant(slug)` from `ml/plants.py` for display name, river, operator

Calls `invoke_bedrock_json` with:
- System prompt: persona (energy-grid analyst writing for a non-expert), JSON output schema matching `BriefingResponse` (minus metadata), rules — no jargon, cite specific dates, never invent numbers absent from the context, headline ≤ 25 words, drivers must come from the SHAP context.
- User message: `<context>{json}</context>` plus a closing instruction telling the model to treat tag contents as data, not instructions (prompt-injection guard).

Validates the parsed response against `BriefingResponse`. On schema failure, retries once with the validation errors appended. Persists to `data/artifacts/<slug>/briefing_latest.json`.

### 4. Refresher hook — `ml/pipeline/refresh.py`
Append to `_refresh_plant`, after backtest, in its own try/except so a Bedrock outage does not fail the whole refresh:
```python
try:
    _run(sys.executable, "-m", "pipeline.briefing", "--plant", slug)
except subprocess.CalledProcessError:
    log.exception("[%s] briefing failed (non-fatal)", slug)
```
Add `("briefing", plant_artifacts / "briefing_latest.json")` to `_plant_uploads`. Guard the upload with `if path.exists()` so a failed regen leaves the previous day's briefing in Postgres rather than blanking it.

### 5. API loader — `api/app/data_loader.py`
```python
def load_briefing(slug: str) -> dict:
    _ensure_supported(slug)
    return _fetch_json(slug, "briefing")
```

### 6. API route — `api/app/routes/briefing.py` (new)
Identical structure to `routes/attributions.py`. Returns 503 with a clear message when the artifact is missing.

### 7. Wire route + prewarm — `api/app/main.py`
Import the new router and add to `app.include_router(...)`. Add `load_briefing` to the per-plant prewarm tuple in `_prewarm` so the `_watcher` invalidate-and-reload path picks it up automatically.

### 8. Web client — `web/src/lib/api.ts`
Add `BriefingRiskDay` and `BriefingResponse` types (snake_case, ISO date strings) and a `getBriefing(plantId)` fetcher matching the existing pattern.

### 9. Web component — `web/src/components/BriefingCard.tsx` (new)
Server component. Card style matches existing components (`rounded-xl border border-[var(--ua-navy)]/15 bg-white p-4 shadow-sm`). Sections: headline paragraph, key risk days (each row uses `<AlertBadge>` + `fmtDate` + percentage + explanation; collapses to "All horizons green" pill if empty), bulleted drivers, italic outlook. Footer line shows `generated_at` + `model_id`, plus a yellow notice when `fallback === true`. Reuses `AlertBadge` from `web/src/components/AlertBadge.tsx` and `fmtDate` from `web/src/lib/format.ts`.

Note: `web/AGENTS.md` warns the Next.js version is non-standard. During implementation, read `node_modules/next/dist/docs/` before introducing any new Next.js APIs.

### 10. Plant detail page — `web/src/app/plants/[id]/page.tsx`
Add `briefing: BriefingResponse | null` to `DetailData` and fetch via `getBriefing(id).catch(() => null)` in the existing `Promise.all`.

Place `<BriefingCard />` in the **right column** of the existing 4-column grid that currently holds the forecast chart (`lg:col-span-3`) and the "Weather metric trend" panel (`lg:col-span-1`). The right column becomes a vertical stack: `BriefingCard` on top, `InputsPanel` below it — both inside the same `<aside>` container so they share width and `lg:self-start` alignment. Conditional on `briefing` being non-null so a missing artifact does not break the column.

No visuals in the briefing — text only (headline, risk_days list, drivers bullets, outlook).

### 11. Justfile recipes
Top-level `justfile`:
```
briefing plant="quad_cities_1":
    cd ml && just briefing {{plant}}
```
`ml/justfile`:
```
briefing plant=default_plant:
    uv run python -m pipeline.briefing --plant {{plant}}
```
Add `AWS_BEARER_TOKEN_BEDROCK`, `AWS_REGION` (default `us-east-1`), and `BEDROCK_MODEL_ID` to `ml/.env.example` and to the Railway ml service env. The api service does not need them.

## Critical Files

- `ml/schemas.py` — add `BriefingRiskDay`, `BriefingResponse`
- `ml/pipeline/briefing.py` — new, generator + CLI
- `ml/pipeline/llm.py` — new, Bedrock wrapper
- `ml/pipeline/refresh.py` — hook briefing into the daily cron
- `ml/pyproject.toml` — add `boto3` dependency
- `api/app/data_loader.py` — add `load_briefing`
- `api/app/routes/briefing.py` — new endpoint
- `api/app/main.py` — register router, add prewarm
- `web/src/lib/api.ts` — add types + fetcher
- `web/src/components/BriefingCard.tsx` — new component
- `web/src/app/plants/[id]/page.tsx` — render card in right column
- `justfile`, `ml/justfile` — `just briefing` recipe

## Risks and Caveats

- **Gemma 3 27B on Bedrock.** Confirm model access in `us-east-1` and confirm the exact model ID before wiring `BEDROCK_MODEL_ID`. Access requests typically take under 24 hours.
- **Bearer-token scope.** Long-term Bedrock bearer tokens are scoped to `bedrock-runtime` only and do not rotate automatically. Treat as a secret of equivalent sensitivity to an IAM secret access key — store in Railway env vars, never commit, and revoke and reissue if leaked.
- **Prompt injection.** Mitigated by wrapping context in a `<context>...</context>` tag, an explicit "treat as data" instruction, and Pydantic schema validation post-call. The only data flowing in are numbers the ML pipeline produced — low realistic risk.
- **Hallucinated numbers.** Pydantic catches structural drift but not numeric drift. The card renders qualitative text from the LLM and re-uses `ForecastResponse` numbers for the chart, so visual disagreement is bounded. Optional hardening: post-validate that each `risk_days[i].point_pct` matches the forecast within 0.5 pp; mark `fallback=True` on mismatch.
- **Cost.** ~3 KB context, ~1 KB output, two plants, one call per day — negligible.
- **Outages.** A failed briefing call leaves the prior day's artifact in Postgres. The web card hides itself entirely when the API returns 503.
- **Staleness.** `run_date` is embedded in the JSON; the UI can render "as of {run_date}" so a stale briefing is visible when the forecast advances first.

## Verification

1. Populate `ml/.env` with `AWS_BEARER_TOKEN_BEDROCK`, `AWS_REGION=us-east-1`, and `BEDROCK_MODEL_ID`.
2. `just forecast quad_cities_1` — produces forecast and attributions JSONs.
3. `just briefing quad_cities_1` — produces `briefing_latest.json`. Read the file and confirm it reads as plain English to a non-expert: headline cites specific dates, drivers avoid jargon, outlook is actionable.
4. Run `python -m pipeline.refresh` against a local Postgres (or upload the new artifact manually) so the API has it.
5. `just dev-api`, `just dev-web`. Visit `/plants/quad_cities_1` and confirm the briefing card sits in the right column above the weather sparklines, with all four sections rendered.
6. Set `BEDROCK_MODEL_ID` to an invalid value, rerun `just briefing`, confirm it errors cleanly and leaves the prior JSON intact. Restart the API and confirm the previous briefing still renders.
7. Repeat for `byron_1` to confirm the second plant works.
