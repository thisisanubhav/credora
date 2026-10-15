"""Capped qualitative advice; the model cannot create an eligible match."""

from __future__ import annotations

import json
import logging
import os
import time

import httpx
from pydantic import BaseModel, ConfigDict, Field

from services.discovery.gemini import DEFAULT_MODEL
from services.eligibility.rules import Decision

LOGGER = logging.getLogger(__name__)
MAX_ADVISORY_CALLS_PER_RUN = 5


class Advice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str = Field(pattern="^(unresolved|unsupported)$")
    explanation_code: str = Field(pattern="^[a-z_]{3,40}$")


def advise(decision: Decision, *, client: httpx.Client | None = None) -> str:
    """Return advisory status only; no promotion from REVIEW_REQUIRED is allowed."""
    if decision.status != "REVIEW_REQUIRED":
        return "not_needed"
    key = os.getenv("GEMINI_API_KEY", "")
    if not key:
        return "unavailable"
    model = os.getenv("GEMINI_MODEL", DEFAULT_MODEL)
    if model != DEFAULT_MODEL:
        return "model_not_verified"
    # No email, external user identifier, raw CSV, or source page is sent.
    prompt = ("A bank condition was not fully decidable from supplied structured data. "
              "Classify it only as unresolved or unsupported. Never claim eligibility. "
              + json.dumps({"reason_codes": [r["code"] for r in decision.reasons]}, sort_keys=True))
    payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {
        "responseFormat": {"text": {"mimeType": "application/json", "schema": {
            "type": "object", "properties": {"status": {"type": "string", "enum": ["unresolved", "unsupported"]},
                                            "explanation_code": {"type": "string"}},
            "required": ["status", "explanation_code"]}}}, "temperature": 0}}
    owned = client is None
    if client is None:
        client = httpx.Client(timeout=httpx.Timeout(12.0, connect=4.0), trust_env=False)
    try:
        for attempt in range(2):
            try:
                response = client.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                    headers={"x-goog-api-key": key}, json=payload,
                )
            except httpx.TransportError:
                if attempt == 0:
                    time.sleep(0.5)
                    continue
                return "transport_failed"
            if response.status_code in (429, 500, 502, 503, 504) and attempt == 0:
                time.sleep(0.5)
                continue
            if response.status_code != 200:
                return "api_failed"
            try:
                data = response.json()
                usage = data.get("usageMetadata", {})
                LOGGER.info("matching advisory tokens input=%s output=%s",
                            usage.get("promptTokenCount"), usage.get("candidatesTokenCount"))
                result = Advice.model_validate_json(data["candidates"][0]["content"]["parts"][0]["text"])
                return result.status
            except (KeyError, IndexError, ValueError):
                return "invalid_response"
        return "transport_failed"
    finally:
        if owned:
            client.close()
