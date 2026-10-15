"""Bounded, testable notification stages invoked by self-hosted n8n."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import ValidationError

from services.common.db import make_engine
from services.eligibility.transport import verify
from services.notifications.storage import (
    accept_event,
    compose,
    mock_send,
    next_reservation,
    record_result,
)

router = APIRouter(prefix="/notifications")


def _call(operation, *args, **kwargs):  # type: ignore[no-untyped-def]
    engine = make_engine()
    try:
        return operation(engine, *args, **kwargs)
    except (ValueError, KeyError, ValidationError) as error:
        raise HTTPException(422, "notification_step_rejected") from error
    finally:
        engine.dispose()


@router.post("/accept")
def accept(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        envelope = verify(payload["body"], payload["headers"], expected_type="matching.completed.v1")
    except (KeyError, ValueError, ValidationError) as error:
        raise HTTPException(401, "invalid_signed_event") from error
    return _call(accept_event, event_id=envelope.event_id, batch_id=envelope.batch_id)


@router.post("/next")
def next_item(payload: dict[str, Any]) -> dict[str, Any]:
    return _call(next_reservation, uuid.UUID(payload["run_id"]))


@router.post("/compose")
def content(payload: dict[str, Any]) -> dict[str, Any]:
    return _call(compose, uuid.UUID(payload["notification_id"]), begin_send=False)


@router.post("/preflight")
def preflight(payload: dict[str, Any]) -> dict[str, Any]:
    return _call(compose, uuid.UUID(payload["notification_id"]), begin_send=True)


@router.post("/mock-send")
def mock(payload: dict[str, Any]) -> dict[str, Any]:
    return _call(mock_send, uuid.UUID(payload["notification_id"]), payload["recipient"])


@router.post("/result")
def result(payload: dict[str, Any]) -> dict[str, Any]:
    return _call(record_result, uuid.UUID(payload["notification_id"]),
                 message_id=payload.get("message_id"), error_code=payload.get("error_code"))
