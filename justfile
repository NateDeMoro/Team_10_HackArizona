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

# Tier 3 model training
train:
    cd ml && just train

# Tier 4 backtest
backtest:
    cd ml && just backtest

# Lint api + web
lint:
    cd web && pnpm lint
