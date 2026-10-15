"""Single-process API→presigned S3 POST→S3-event worker→PostgreSQL replay check."""

from __future__ import annotations

import uuid

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from apps.api.main import app
from scripts.local_s3 import ensure_bucket
from services.common.db import make_engine, session_scope
from services.common.models import OutboxEvent, UploadBatch, User
from services.ingestion.config import Settings, s3_client
from services.ingestion.worker import lambda_handler


def main() -> None:
    ensure_bucket()
    content = ("user_id,email,monthly_income,credit_score,employment_status,age\n"
               "e2e-one,one@example.com,42000.25,710,Salaried,30\n"
               "e2e-two,two@example.com,35000,680,Self-Employed,41\n")
    with TestClient(app) as api:
        created = api.post("/uploads", headers={"Idempotency-Key": str(uuid.uuid4())}, json={
            "filename": "users.csv", "size_bytes": len(content.encode()), "content_type": "text/csv",
        })
        assert created.status_code == 201, created.status_code
        payload = created.json()
        batch_id = uuid.UUID(payload["batch_id"])
        upload = payload["upload"]
        response = httpx.post(upload["url"], data=upload["fields"], files={
            "file": ("users.csv", content.encode(), "text/csv"),
        }, timeout=30)
        assert response.status_code in (200, 201, 204), response.status_code
        settings = Settings.from_env()
        client = s3_client(settings)
        key = upload["fields"]["key"]
        etag = client.head_object(Bucket=settings.bucket, Key=key)["ETag"].strip('"')
        event = {"Records": [{"eventName": "ObjectCreated:Post", "s3": {
            "bucket": {"name": settings.bucket}, "object": {"key": key, "eTag": etag},
        }}]}
        assert lambda_handler(event, None)["results"] == ["processed"]
        assert lambda_handler(event, None)["results"] == ["already_complete"]
        status = api.get(f"/uploads/{batch_id}")
        assert status.status_code == 200
        assert status.json()["status"] == "processed"
        assert status.json()["accepted_rows"] == 2
        engine = make_engine()
        try:
            with session_scope(engine) as session:
                assert session.scalar(select(func.count()).select_from(User).where(User.upload_batch_id == batch_id)) == 2
                assert session.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.aggregate_id == batch_id)) == 1
                assert session.get(UploadBatch, batch_id).rejected_rows == 0
        finally:
            engine.dispose()
    print("PASS: local API→S3→worker→database→outbox; replay created no duplicates.")


if __name__ == "__main__":
    main()
