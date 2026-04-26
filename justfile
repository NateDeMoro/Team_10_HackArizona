set dotenv-load := true

# Local dev: FastAPI on :8000 with autoreload
dev-api:
    cd api && uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Local dev: Next.js on :3000
dev-web:
    cd web && pnpm dev

# Tier 0 ml smoke test
ml-no-op:
    cd ml && just no-op

# Tier 1 label ingest. `just ingest-labels byron_1` for a non-default plant.
ingest-labels plant="quad_cities_1":
    cd ml && just ingest-labels {{plant}}

# Tier 2 feature build. `just features byron_1` for a non-default plant.
features plant="quad_cities_1":
    cd ml && just features {{plant}}

# Tier 3 model training. `just train byron_1` for a non-default plant.
train plant="quad_cities_1":
    cd ml && just train {{plant}}

# Tier 4 backtest. `just backtest byron_1` for a non-default plant.
backtest plant="quad_cities_1":
    cd ml && just backtest {{plant}}

# Tier 4 forecast: refresh the precomputed JSON the API serves.
# `just forecast byron_1` for a non-default plant.
forecast plant="quad_cities_1":
    cd ml && just forecast {{plant}}

# Lint api + web
lint:
    cd web && pnpm lint
