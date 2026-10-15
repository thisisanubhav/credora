"""Internal-only step endpoints; n8n owns Workflow A sequencing and branching."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import ValidationError

from services.common.db import make_engine
from services.discovery.crawler import CrawlError, fetch_source
from services.discovery.extraction import (
    PageEvidence,
    ProductCandidate,
    extract_deterministic,
    validate_candidate,
)
from services.discovery.gemini import GeminiError, structure_qualitative
from services.discovery.persistence import mark_attempt, persist_product, record_source, start_run
from services.discovery.sources import SOURCES, require_source

app = FastAPI(title="Internal Discovery Steps", docs_url=None, redoc_url=None)


def _engine():  # type: ignore[no-untyped-def]
    return make_engine()


def _failed(payload: dict[str, Any], code: str) -> dict[str, Any]:
    return {"run_id": payload.get("run_id"), "source_key": payload.get("source_key"),
            "status": "failed", "error_code": code}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/discovery/runs")
def create_run() -> dict[str, Any]:
    engine = _engine()
    try:
        run_id = start_run(engine)
        return {"run_id": str(run_id), "source_keys": list(SOURCES)}
    finally:
        engine.dispose()


@app.post("/discovery/fetch")
def fetch(payload: dict[str, Any]) -> dict[str, Any]:
    key = str(payload.get("source_key", ""))
    try:
        require_source(key)
    except ValueError as error:
        raise HTTPException(422, "source_not_allowlisted") from error
    engine = _engine()
    try:
        mark_attempt(engine, key)
    finally:
        engine.dispose()
    try:
        page = fetch_source(key)
    except CrawlError as error:
        return _failed(payload, str(error))
    return {"run_id": payload.get("run_id"), "source_key": key,
            "status": "ok", "page": page}


@app.post("/discovery/extract")
def extract(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("status") != "ok":
        return payload
    try:
        page = PageEvidence.model_validate(payload["page"])
        candidate = extract_deterministic(page)
    except (KeyError, ValueError, ValidationError):
        return _failed(payload, "deterministic_extraction_failed")
    return {"run_id": payload["run_id"], "source_key": page.source_key,
            "status": "ok", "page": page.model_dump(mode="json"),
            "candidate": candidate.model_dump(mode="json"),
            "needs_llm": bool(candidate.eligibility_rules.ambiguous)}


@app.post("/discovery/gemini")
def gemini(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("status") != "ok" or not payload.get("needs_llm"):
        return payload
    try:
        page = PageEvidence.model_validate(payload["page"])
        candidate = ProductCandidate.model_validate(payload["candidate"])
        candidate, llm_status = structure_qualitative(candidate, page)
        return {**payload, "candidate": candidate.model_dump(mode="json"), "llm_status": llm_status}
    except (KeyError, ValueError, ValidationError, GeminiError):
        # Preserve deterministic extraction; an LLM failure never manufactures rules.
        return {**payload, "llm_status": "failed"}


@app.post("/discovery/validate")
def validate(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("status") != "ok":
        return payload
    try:
        page = PageEvidence.model_validate(payload["page"])
        candidate = validate_candidate(ProductCandidate.model_validate(payload["candidate"]), page)
    except (KeyError, ValueError, ValidationError):
        return _failed(payload, "source_evidence_validation_failed")
    return {"run_id": payload["run_id"], "source_key": page.source_key,
            "status": "validated", "candidate": candidate.model_dump(mode="json"),
            "llm_status": payload.get("llm_status", "not_needed")}


@app.post("/discovery/persist")
def persist(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("status") != "validated":
        return {**payload, "outcome": "failed"}
    try:
        candidate = ProductCandidate.model_validate(payload["candidate"])
        engine = _engine()
        try:
            outcome, product_id, version = persist_product(engine, candidate)
        finally:
            engine.dispose()
    except (ValueError, ValidationError):
        return _failed(payload, "product_persistence_validation_failed") | {"outcome": "failed"}
    return {"run_id": payload["run_id"], "source_key": payload["source_key"],
            "status": "persisted", "outcome": outcome,
            "product_id": str(product_id), "version": version,
            "verification_status": candidate.verification_status,
            "llm_status": payload.get("llm_status", "not_needed")}


@app.post("/discovery/record")
def record(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        run_id = uuid.UUID(str(payload["run_id"]))
        key = str(payload["source_key"])
    except (KeyError, ValueError) as error:
        raise HTTPException(422, "invalid_discovery_run") from error
    outcome = str(payload.get("outcome", "failed"))
    engine = _engine()
    try:
        result = record_source(engine, run_id, key, outcome)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    finally:
        engine.dispose()
    return {**result, "product_id": payload.get("product_id"),
            "version": payload.get("version"),
            "verification_status": payload.get("verification_status"),
            "llm_status": payload.get("llm_status", "not_needed"),
            "error_code": payload.get("error_code")}
