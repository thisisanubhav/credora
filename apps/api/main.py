"""Minimal loopback upload API; deployment authentication belongs to a later milestone."""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid

from fastapi import FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from services.common.db import make_engine, session_scope
from services.common.models import UploadBatch, UploadRowError
from services.ingestion.config import Settings, s3_client

app = FastAPI(title="Loan Eligibility Upload API", docs_url=None, redoc_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("FRONTEND_ORIGIN", "http://localhost:3000")],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Idempotency-Key"],
    allow_credentials=False,
)


class UploadRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(gt=0)
    content_type: str
    demo_mode: bool = False


def _settings() -> Settings:
    return Settings.from_env()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/uploads", status_code=status.HTTP_201_CREATED)
def create_upload(
    request: UploadRequest, idempotency_key: str = Header(min_length=8, max_length=128),
) -> dict[str, object]:
    settings = _settings()
    if request.size_bytes > settings.max_bytes:
        raise HTTPException(413, "CSV exceeds configured upload limit")
    if not re.fullmatch(r"[^/\\\x00-\x1f]+\.csv", request.filename, re.IGNORECASE):
        raise HTTPException(422, "filename must end in .csv and contain no path")
    if request.content_type not in {"text/csv", "application/csv"}:
        raise HTTPException(415, "content_type must be text/csv or application/csv")
    if request.demo_mode and os.getenv("ALLOW_SYNTHETIC_DEMO") != "1":
        raise HTTPException(403, "synthetic demo uploads are disabled")
    key_hash = hashlib.sha256(idempotency_key.encode()).hexdigest()
    fingerprint = hashlib.sha256(json.dumps(request.model_dump(), sort_keys=True).encode()).hexdigest()
    engine = make_engine()
    try:
        with session_scope(engine) as session:
            batch = session.scalar(select(UploadBatch).where(UploadBatch.idempotency_key_hash == key_hash))
            if batch is None:
                batch_id = uuid.uuid4()
                batch = UploadBatch(
                    id=batch_id, object_bucket=settings.bucket,
                    object_key=f"uploads/{batch_id}/{uuid.uuid4().hex}.csv",
                    schema_version=1, idempotency_key_hash=key_hash,
                    request_fingerprint=fingerprint, is_demo=request.demo_mode,
                )
                session.add(batch)
                try:
                    session.flush()
                except IntegrityError:
                    raise HTTPException(409, "Idempotency key was used concurrently; retry request") from None
            elif batch.request_fingerprint != fingerprint:
                raise HTTPException(409, "Idempotency key already used for different metadata")
            elif batch.status != "uploaded":
                raise HTTPException(409, "Upload batch is already processing or complete")
            response = s3_client(settings).generate_presigned_post(
                Bucket=batch.object_bucket, Key=batch.object_key,
                Fields={"Content-Type": "text/csv"},
                Conditions=[{"Content-Type": "text/csv"}, ["content-length-range", 1, settings.max_bytes]],
                ExpiresIn=settings.url_ttl_seconds,
            )
            return {"batch_id": str(batch.id), "upload": response, "expires_in": settings.url_ttl_seconds}
    finally:
        engine.dispose()


@app.get("/uploads/{batch_id}")
def get_upload(batch_id: uuid.UUID) -> dict[str, object]:
    engine = make_engine()
    try:
        with session_scope(engine) as session:
            batch = session.get(UploadBatch, batch_id)
            if batch is None:
                raise HTTPException(404, "Upload batch not found")
            return {
                "batch_id": str(batch.id), "status": batch.status,
                "total_rows": batch.total_rows, "accepted_rows": batch.accepted_rows,
                "rejected_rows": batch.rejected_rows, "errors": batch.error_summary or {},
            }
    finally:
        engine.dispose()


@app.get("/uploads/{batch_id}/errors")
def get_upload_errors(batch_id: uuid.UUID, offset: int = 0, limit: int = 100) -> dict[str, object]:
    if offset < 0 or not 1 <= limit <= 500:
        raise HTTPException(422, "offset must be nonnegative and limit must be 1–500")
    engine = make_engine()
    try:
        with session_scope(engine) as session:
            if session.get(UploadBatch, batch_id) is None:
                raise HTTPException(404, "Upload batch not found")
            rows = session.scalars(select(UploadRowError).where(
                UploadRowError.upload_batch_id == batch_id,
            ).order_by(UploadRowError.row_number).offset(offset).limit(limit)).all()
            return {"batch_id": str(batch_id), "errors": [
                {"row": item.row_number, "codes": item.codes} for item in rows
            ], "offset": offset, "limit": limit}
    finally:
        engine.dispose()
