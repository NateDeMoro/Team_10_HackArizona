"""Bedrock wrapper for the briefing generator.

Use when: a pipeline step needs to invoke a Bedrock chat model and get
back a JSON object. Today only `pipeline.briefing` calls in here, but the
public surface is intentionally generic so future LLM-touching tiers can
share auth + retry behavior.

Auth: long-term Bedrock bearer token via `AWS_BEARER_TOKEN_BEDROCK`.
boto3 picks the env var up natively for the `bedrock-runtime` service —
no IAM access key / secret pair, no signing config. Requires
`boto3>=1.39` (the version that introduced bearer-token auth for
Bedrock). The api service does not depend on boto3; this module is
ml-side only and the api serves cached briefing bytes.
"""
from __future__ import annotations

import json
import logging
import os
import time

log = logging.getLogger(__name__)

# Single retry on throttling / 5xx. Bedrock occasionally throttles fresh
# bearer tokens or surfaces transient 5xx — one retry covers the common
# case without masking real outages.
_RETRY_STATUS_PREFIX = ("Throttling", "ThrottlingException", "ServiceUnavailable")
_RETRY_BACKOFF_S = 2.0


class BriefingError(RuntimeError):
    """Raised when Bedrock fails after retries or returns malformed JSON."""


def invoke_bedrock_json(
    *,
    system: str,
    user: str,
    model_id: str,
    region: str,
    max_tokens: int = 1500,
    timeout_s: float = 30.0,
) -> dict:
    """Invoke a Bedrock chat model and parse its response as JSON.

    Returns the parsed dict. Raises BriefingError on transport failure,
    non-2xx response, or unparseable JSON. The caller is responsible for
    pydantic-validating the dict against its expected schema.
    """
    try:
        import boto3  # noqa: PLC0415  - lazy import so api/ doesn't need boto3
        from botocore.config import Config  # noqa: PLC0415
    except ImportError as exc:
        raise BriefingError(
            "boto3 not installed; add boto3>=1.39 to ml/pyproject.toml"
        ) from exc

    if not os.environ.get("AWS_BEARER_TOKEN_BEDROCK"):
        raise BriefingError(
            "AWS_BEARER_TOKEN_BEDROCK is not set; bearer-token auth is required"
        )

    config = Config(
        connect_timeout=timeout_s,
        read_timeout=timeout_s,
        retries={"max_attempts": 1, "mode": "standard"},
    )
    client = boto3.client("bedrock-runtime", region_name=region, config=config)

    body = {
        "messages": [{"role": "user", "content": [{"text": user}]}],
        "system": [{"text": system}],
        "inferenceConfig": {"maxTokens": max_tokens, "temperature": 0.2},
    }

    last_exc: Exception | None = None
    for attempt in (1, 2):
        try:
            resp = client.converse(modelId=model_id, **body)
            break
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            name = type(exc).__name__
            if attempt == 1 and any(name.startswith(p) for p in _RETRY_STATUS_PREFIX):
                log.warning("bedrock retryable error (%s); backing off", name)
                time.sleep(_RETRY_BACKOFF_S)
                continue
            raise BriefingError(f"bedrock invoke failed: {exc}") from exc
    else:
        raise BriefingError(f"bedrock invoke failed after retries: {last_exc}")

    try:
        text_chunks = resp["output"]["message"]["content"]
        text = "".join(c.get("text", "") for c in text_chunks).strip()
    except (KeyError, TypeError) as exc:
        raise BriefingError(f"unexpected bedrock response shape: {resp!r}") from exc

    payload = _extract_json(text)
    if not isinstance(payload, dict):
        raise BriefingError(f"bedrock response was not a JSON object: {text!r}")
    return payload


def _extract_json(text: str) -> object:
    """Parse the model's output as JSON, tolerating fenced code blocks."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # Strip the opening fence and optional language tag, then the
        # trailing fence. The model occasionally wraps JSON despite the
        # explicit instruction not to.
        first_nl = cleaned.find("\n")
        if first_nl != -1:
            cleaned = cleaned[first_nl + 1 :]
        if cleaned.endswith("```"):
            cleaned = cleaned[: -3]
        cleaned = cleaned.strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise BriefingError(f"bedrock returned non-JSON text: {text!r}") from exc
