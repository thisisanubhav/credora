"""Canonical HMAC envelope shared by the local dispatcher and n8n verifier."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class ReadyEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: uuid.UUID
    event_type: Literal["upload_batch.ready.v1"]
    batch_id: uuid.UUID


def canonical_body(body: dict[str, Any]) -> bytes:
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode()


def signature(body: dict[str, Any], timestamp: str, secret: str) -> str:
    return hmac.new(secret.encode(), timestamp.encode() + b"." + canonical_body(body), hashlib.sha256).hexdigest()


def verify(body: dict[str, Any], headers: dict[str, str]) -> ReadyEnvelope:
    secret = os.environ.get("MATCHING_WEBHOOK_SECRET", "")
    if len(secret) < 32:
        raise ValueError("webhook_secret_unconfigured")
    normalized = {key.lower(): value for key, value in headers.items()}
    timestamp = normalized.get("x-loan-timestamp", "")
    supplied = normalized.get("x-loan-signature", "")
    try:
        instant = datetime.fromtimestamp(int(timestamp), UTC)
    except (ValueError, OverflowError) as error:
        raise ValueError("invalid_webhook_timestamp") from error
    if abs((datetime.now(UTC) - instant).total_seconds()) > 300:
        raise ValueError("webhook_timestamp_expired")
    expected = signature(body, timestamp, secret)
    if not hmac.compare_digest(supplied, expected):
        raise ValueError("invalid_webhook_signature")
    envelope = ReadyEnvelope.model_validate(body)
    if normalized.get("x-loan-event-id") != str(envelope.event_id):
        raise ValueError("event_header_mismatch")
    return envelope
