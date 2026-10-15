"""Small n8n-invoked matching stages; no single opaque batch processor."""

from __future__ import annotations

import os
import uuid
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import ValidationError

from services.common.db import make_engine
from services.eligibility.gemini import MAX_ADVISORY_CALLS_PER_RUN, advise
from services.eligibility.rules import Decision, ProductFacts, UserFacts, evaluate
from services.eligibility.storage import (
    accept_event,
    batch_summary,
    candidate_page,
    complete_run,
    persist_page,
    reserve_llm_call,
)
from services.eligibility.transport import verify

router = APIRouter(prefix="/matching")


def _engine():  # type: ignore[no-untyped-def]
    return make_engine()


@router.post("/accept")
def accept(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        envelope = verify(payload["body"], payload["headers"])
    except (KeyError, ValueError, ValidationError) as error:
        raise HTTPException(401, "invalid_signed_event") from error
    engine = _engine()
    try:
        return accept_event(engine, event_id=envelope.event_id, batch_id=envelope.batch_id)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    finally:
        engine.dispose()


@router.post("/batch")
def batch(payload: dict[str, Any]) -> dict[str, Any]:
    engine = _engine()
    try:
        return batch_summary(engine, uuid.UUID(payload["run_id"]))
    finally:
        engine.dispose()


@router.post("/candidates")
def candidates(payload: dict[str, Any]) -> dict[str, Any]:
    engine = _engine()
    try:
        return candidate_page(engine, uuid.UUID(payload["run_id"]), payload.get("cursor"))
    finally:
        engine.dispose()


@router.post("/evaluate")
def evaluate_page(payload: dict[str, Any]) -> dict[str, Any]:
    decisions = []
    try:
        for pair in payload["candidates"]:
            data = dict(pair["user"])
            data["monthly_income"] = Decimal(data["monthly_income"]) if data["monthly_income"] is not None else None
            user = UserFacts.model_validate(data)
            product = ProductFacts.model_validate(pair["product"])
            decisions.append(evaluate(user, product, demo_batch=payload["demo_batch"]).model_dump(mode="json"))
    except (KeyError, ValueError, ValidationError) as error:
        raise HTTPException(422, "invalid_candidate_page") from error
    return {"run_id": payload["run_id"], "cursor": payload.get("cursor"),
            "next_cursor": payload.get("next_cursor"), "decisions": decisions}


@router.post("/gemini")
def advisory_page(payload: dict[str, Any]) -> dict[str, Any]:
    decisions = [Decision.model_validate(item) for item in payload["decisions"]]
    statuses: list[str] = []
    engine = _engine()
    try:
        for item in decisions:
            if item.status != "REVIEW_REQUIRED":
                statuses.append("not_needed")
            elif not os.environ.get("GEMINI_API_KEY"):
                statuses.append("unavailable")
            elif not reserve_llm_call(engine, uuid.UUID(payload["run_id"]), MAX_ADVISORY_CALLS_PER_RUN):
                statuses.append("budget_exhausted")
            else:
                statuses.append(advise(item))
                item.llm_involved = True
    finally:
        engine.dispose()
    return {**payload, "decisions": [item.model_dump(mode="json") for item in decisions],
            "advisory_statuses": statuses}


@router.post("/persist")
def persist(payload: dict[str, Any]) -> dict[str, Any]:
    engine = _engine()
    try:
        return persist_page(engine, uuid.UUID(payload["run_id"]), payload.get("cursor"),
                            payload.get("next_cursor"), [Decision.model_validate(item) for item in payload["decisions"]])
    finally:
        engine.dispose()


@router.post("/complete")
def complete(payload: dict[str, Any]) -> dict[str, Any]:
    engine = _engine()
    try:
        return complete_run(engine, uuid.UUID(payload["run_id"]), payload.get("cursor"))
    finally:
        engine.dispose()
