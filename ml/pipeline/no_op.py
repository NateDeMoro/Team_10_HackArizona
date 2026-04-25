"""Tier 0 end-to-end smoke test: imports and invokes every stub.
Use when verifying the pipeline scaffold is wired correctly."""
import logging

from pipeline import (
    backtest,
    baselines,
    build_dataset,
    features,
    ingest_eia,
    ingest_nrc,
    ingest_usgs,
    ingest_weather,
    inference,
    train,
)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(name)s %(message)s")
    for mod in (
        ingest_nrc,
        ingest_eia,
        ingest_weather,
        ingest_usgs,
        features,
        build_dataset,
        baselines,
        train,
        backtest,
        inference,
    ):
        mod.run()
    print("ok")


if __name__ == "__main__":
    main()
