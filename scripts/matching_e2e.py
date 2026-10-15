"""Real API→S3→worker→signed n8n webhook→matches local demonstration."""

from __future__ import annotations

import os
import time
import uuid

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from apps.api.main import app
from scripts.local_s3 import ensure_bucket
from services.common.db import make_engine, session_scope
from services.common.models import (
    LoanProduct,
    Match,
    OutboxEvent,
    ProductSource,
    UploadBatch,
    User,
    WorkflowExecution,
)
from services.eligibility.dispatcher import dispatch_once
from services.eligibility.transport import signature
from services.ingestion.config import Settings, s3_client
from services.ingestion.worker import lambda_handler


def main() -> None:
    if os.environ.get("ALLOW_SYNTHETIC_DEMO") != "1":
        raise RuntimeError("local synthetic demo is disabled")
    ensure_bucket()
    content = (b"user_id,email,monthly_income,credit_score,employment_status,age\n"
               b"demo-pass,pass@example.com,50000,710,Salaried,30\n"
               b"demo-score,score@example.com,50000,699,Salaried,30\n"
               b"demo-age,age@example.com,50000,710,Salaried,24\n"
               b"demo-employment,employment@example.com,50000,710,Self-Employed,30\n")
    with TestClient(app) as api:
        created = api.post("/uploads", headers={"Idempotency-Key": str(uuid.uuid4())}, json={
            "filename": "synthetic-demo.csv", "size_bytes": len(content),
            "content_type": "text/csv", "demo_mode": True,
        })
        assert created.status_code == 201, created.status_code
        payload = created.json()
        batch_id = uuid.UUID(payload["batch_id"])
        upload = payload["upload"]
        response = httpx.post(upload["url"], data=upload["fields"],
                              files={"file": ("synthetic-demo.csv", content, "text/csv")}, timeout=30)
        assert response.status_code in (200, 201, 204), response.status_code
        settings = Settings.from_env()
        key = upload["fields"]["key"]
        etag = s3_client(settings).head_object(Bucket=settings.bucket, Key=key)["ETag"].strip('"')
        event = {"Records": [{"eventName": "ObjectCreated:Post", "s3": {
            "bucket": {"name": settings.bucket}, "object": {"key": key, "eTag": etag},
        }}]}
        assert lambda_handler(event, None)["results"] == ["processed"]
        engine = make_engine()
        try:
            with session_scope(engine) as session:
                ready = session.scalar(select(OutboxEvent).where(
                    OutboxEvent.aggregate_id == batch_id,
                    OutboxEvent.event_type == "upload_batch.ready.v1"))
                assert ready is not None and ready.status == "pending"
                event_id = ready.event_id
            outcome = dispatch_once(engine, only_event_id=event_id)
            assert outcome == "delivered", outcome
            deadline = time.monotonic() + 60
            while True:
                with session_scope(engine) as session:
                    batch = session.get(UploadBatch, batch_id)
                    assert batch is not None
                    runs = session.scalars(select(WorkflowExecution).where(
                        WorkflowExecution.upload_batch_id == batch_id,
                        WorkflowExecution.workflow_type == "matching")).all()
                    if batch.status == "matched":
                        break
                if time.monotonic() > deadline:
                    raise RuntimeError(f"matching workflow did not finish; batch={batch.status}; runs={[(r.status,r.error_code) for r in runs]}")
                time.sleep(1)
            with session_scope(engine) as session:
                matches = session.scalars(select(Match).join(User, Match.user_id == User.id).where(
                    User.upload_batch_id == batch_id)).all()
                assert len(matches) == 1
                product = session.get(LoanProduct, matches[0].product_id)
                assert product is not None
                source = session.get(ProductSource, product.source_id)
                assert source is not None and source.source_type == "synthetic"
                assert session.scalar(select(func.count()).select_from(Match).join(
                    LoanProduct, Match.product_id == LoanProduct.id).join(
                    ProductSource, LoanProduct.source_id == ProductSource.id).join(
                    User, Match.user_id == User.id).where(User.upload_batch_id == batch_id,
                    ProductSource.source_type == "official")) == 0
                assert session.scalar(select(func.count()).select_from(OutboxEvent).where(
                    OutboxEvent.aggregate_id == batch_id,
                    OutboxEvent.event_type == "matching.completed.v1")) == 1
                run = runs[0]
                print(f"PASS: batch={batch_id} run={run.id} candidates={run.metrics['candidates']} matches={len(matches)} llm_calls={run.metrics['llm_calls']}")
            body = {"event_id": str(event_id), "event_type": "upload_batch.ready.v1", "batch_id": str(batch_id)}
            timestamp = str(int(time.time()))
            response = httpx.post(os.environ["MATCHING_WEBHOOK_URL"], json=body, headers={
                "X-Loan-Event-Id": str(event_id), "X-Loan-Timestamp": timestamp,
                "X-Loan-Signature": signature(body, timestamp, os.environ["MATCHING_WEBHOOK_SECRET"]),
            }, timeout=30)
            assert response.status_code == 202 and response.json()["state"] == "complete", response.status_code
            with session_scope(engine) as session:
                assert session.scalar(select(func.count()).select_from(Match).join(User).where(
                    User.upload_batch_id == batch_id)) == 1
            print("PASS: duplicate signed webhook created no new match or completion event; official products remained unmatched.")
        finally:
            engine.dispose()


if __name__ == "__main__":
    main()
