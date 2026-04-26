FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --frozen

# Source + baked-in static data. The refresher regenerates raw/processed
# at run time, but interim and artifacts ship in the image so api keeps
# serving even if the very first refresher run fails.
COPY plants.py schemas.py ./
COPY pipeline ./pipeline
COPY data ./data

CMD ["uv", "run", "python", "-m", "pipeline.refresh"]
