from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes import (
    actuals,
    attributions,
    backtest,
    briefing,
    forecast,
    history,
    inputs,
    plants,
)

log = logging.getLogger("api.main")

# How often the watcher polls Postgres for a fresh refreshed_at. The
# refresher cron runs once a day, so 60s is responsive enough without
# putting meaningful load on the DB (one trivial SELECT per minute).
WATCH_POLL_SECONDS = 60


def _prewarm() -> None:
    """Pull every artifact the api serves into the byte cache.

    Runs synchronously in a worker thread (kicked off from ``lifespan``).
    Failures are logged and swallowed so a single bad fetch never blocks
    the rest. The first user request after this completes hits a hot
    cache for everything except whatever specifically failed.
    """
    from app.data_loader import (
        SUPPORTED_PLANTS,
        load_attributions,
        load_backtest_dates,
        load_backtest_metrics,
        load_briefing,
        load_eia_plants,
        load_forecast,
        load_recent_actuals,
        load_recent_inputs,
    )

    log.info("prewarm: starting")
    try:
        load_eia_plants()
    except Exception:  # noqa: BLE001
        log.exception("prewarm: load_eia_plants failed")

    for slug in sorted(SUPPORTED_PLANTS):
        for label, call in (
            ("forecast",         lambda s=slug: load_forecast(s)),
            ("attributions",     lambda s=slug: load_attributions(s)),
            ("briefing",         lambda s=slug: load_briefing(s)),
            ("backtest_metrics", lambda s=slug: load_backtest_metrics(s)),
            ("backtest_results", lambda s=slug: load_backtest_dates(s)),
            ("labels",           lambda s=slug: load_recent_actuals(s, 30)),
            ("weather+water",    lambda s=slug: load_recent_inputs(s, 30)),
        ):
            try:
                call()
            except Exception:  # noqa: BLE001
                log.warning("prewarm: %s/%s failed (will be lazy-loaded)", slug, label)
    log.info("prewarm: done")


async def _watcher() -> None:
    """Daily cache refresh tied to the cron.

    Polls ``MAX(refreshed_at)`` once per minute. When it advances (the ml
    refresher just finished its upload), invalidate the byte cache and
    immediately re-prewarm so users hit hot data, not cold lookups.
    """
    from app.db import clear_cache, latest_refreshed_at

    last_seen = await asyncio.to_thread(latest_refreshed_at)
    log.info("watcher: initial refreshed_at=%s", last_seen)

    while True:
        await asyncio.sleep(WATCH_POLL_SECONDS)
        try:
            current = await asyncio.to_thread(latest_refreshed_at)
        except Exception:  # noqa: BLE001
            log.exception("watcher: poll failed")
            continue
        if current is not None and current != last_seen:
            log.info("watcher: refreshed_at moved %s -> %s; reprewarming", last_seen, current)
            clear_cache()
            await asyncio.to_thread(_prewarm)
            last_seen = current


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Kick prewarm off in a worker thread so uvicorn isn't blocked from
    # accepting requests while the initial DB pulls happen.
    prewarm_task = asyncio.create_task(asyncio.to_thread(_prewarm))
    watcher_task = asyncio.create_task(_watcher())
    try:
        yield
    finally:
        watcher_task.cancel()
        prewarm_task.cancel()


app = FastAPI(title="Derating Forecast API", version="0.1.0", lifespan=lifespan)

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
app.include_router(briefing.router)
app.include_router(history.router)
