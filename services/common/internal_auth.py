"""HMAC authentication and durable replay fencing for private n8n step calls."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Engine

from services.common.db import session_scope
from services.common.models import InternalRequestNonce

WINDOW_SECONDS = 300


def canonical_body(body: dict[str, Any]) -> str:
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sign(body: dict[str, Any], *, key_id: str, timestamp: str, nonce: str,
         method: str, path: str, secret: str) -> str:
    message = f"{key_id}\n{timestamp}\n{nonce}\n{method}\n{path}\n{canonical_body(body)}"
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


def verify_and_reserve(engine: Engine, body: dict[str, Any], headers: dict[str, str],
                       *, method: str, path: str) -> bool:
    """Return false for invalid/replayed requests without exposing a failure oracle."""
    active_id = os.getenv("INTERNAL_STEP_KEY_ID", "")
    active_secret = os.getenv("INTERNAL_STEP_SECRET", "")
    previous_id = os.getenv("INTERNAL_STEP_PREVIOUS_KEY_ID", "")
    previous_secret = os.getenv("INTERNAL_STEP_PREVIOUS_SECRET", "")
    if not active_id or len(active_secret) < 32:
        return False
    keys = {active_id: active_secret}
    if (previous_id and len(previous_secret) >= 32 and previous_id != active_id
            and previous_secret != active_secret):
        keys[previous_id] = previous_secret
    normalized = {key.lower(): value for key, value in headers.items()}
    key_id = normalized.get("x-internal-key-id", "")
    timestamp = normalized.get("x-internal-timestamp", "")
    nonce = normalized.get("x-internal-nonce", "")
    supplied = normalized.get("x-internal-signature", "")
    if key_id not in keys or len(supplied) != 64:
        return False
    try:
        instant = datetime.fromtimestamp(int(timestamp), UTC)
        parsed_nonce = uuid.UUID(nonce)
    except (ValueError, OverflowError):
        return False
    if nonce != str(parsed_nonce) or abs(time.time() - instant.timestamp()) > WINDOW_SECONDS:
        return False
    expected = sign(body, key_id=key_id, timestamp=timestamp, nonce=nonce,
                    method=method, path=path, secret=keys[key_id])
    if not hmac.compare_digest(supplied, expected):
        return False
    with session_scope(engine) as session:
        inserted = session.execute(insert(InternalRequestNonce).values(
            key_id=key_id, nonce=nonce, expires_at=instant + timedelta(seconds=WINDOW_SECONDS),
        ).on_conflict_do_nothing().returning(InternalRequestNonce.nonce)).scalar_one_or_none()
        if parsed_nonce.int & 255 == 0:
            # Amortized cleanup; never remove a nonce in the accepted time window.
            session.execute(delete(InternalRequestNonce).where(
                InternalRequestNonce.expires_at < datetime.now(UTC) - timedelta(hours=1)))
    return inserted is not None
