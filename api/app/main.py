from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes import actuals, attributions, backtest, forecast, inputs, plants

app = FastAPI(title="Derating Forecast API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(plants.router)
app.include_router(forecast.router)
app.include_router(backtest.router)
app.include_router(actuals.router)
app.include_router(inputs.router)
app.include_router(attributions.router)
