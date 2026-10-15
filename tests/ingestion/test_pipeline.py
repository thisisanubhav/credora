"""M3 tests use only the guarded *_test PostgreSQL database and local S3 emulator."""

from __future__ import annotations

import importlib
import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from scripts import local_ingestion_bridge
from scripts.local_s3 import ensure_bucket
from services.common.db import make_engine, session_scope
from services.common.models import OutboxEvent, UploadBatch, UploadRowError, User
from services.ingestion.config import Settings, s3_client
from services.ingestion.worker import (
    FileRejected,
    LimitedStream,
    lambda_handler,
    process_object,
    validate_row,
)

api_module = importlib.import_module("apps.api.main")
worker_module = importlib.import_module("services.ingestion.worker")
HEADER = "user_id,email,monthly_income,credit_score,employment_status,age\n"
VALID = "one,one@example.com,1234.56,700,Salaried,30\n"


@pytest.fixture(scope="module")
def db_engine():
    name = os.environ["TEST_DB_NAME"].removesuffix("_test") + "_ingestion_test"
    assert name.endswith("_test") and name not in {os.environ["POSTGRES_DB"], os.environ["N8N_DB_NAME"]}
    old = os.environ.get("DATABASE_NAME")
    os.environ["DATABASE_NAME"] = name
    command.upgrade(Config("database/alembic.ini"), "head")
    engine = make_engine(role="migration", database=name)
    yield engine
    engine.dispose()
    if old is None:
        os.environ.pop("DATABASE_NAME", None)
    else:
        os.environ["DATABASE_NAME"] = old


@pytest.fixture
def pipeline(db_engine, monkeypatch):
    monkeypatch.setattr(api_module, "make_engine", lambda: db_engine)
    monkeypatch.setattr(worker_module, "make_engine", lambda: db_engine)
    ensure_bucket()
    with TestClient(api_module.app) as client:
        yield client, db_engine


def upload(pipeline, content: bytes, *, filename: str = "users.csv"):
    client, engine = pipeline
    response = client.post("/uploads", headers={"Idempotency-Key": str(uuid.uuid4())}, json={
        "filename": filename, "size_bytes": max(1, len(content)), "content_type": "text/csv",
    })
    assert response.status_code == 201
    batch_id = uuid.UUID(response.json()["batch_id"])
    with session_scope(engine) as session:
        batch = session.get(UploadBatch, batch_id)
        assert batch is not None
        key = batch.object_key
    settings = Settings.from_env()
    s3_client(settings).put_object(Bucket=settings.bucket, Key=key, Body=content)
    return batch_id, key


def inspect_batch(engine, batch_id):
    with session_scope(engine) as session:
        batch = session.get(UploadBatch, batch_id)
        users = session.scalars(select(User).where(User.upload_batch_id == batch_id)).all()
        events = session.scalars(select(OutboxEvent).where(OutboxEvent.aggregate_id == batch_id)).all()
        return batch.status, batch.total_rows, batch.accepted_rows, batch.rejected_rows, batch.error_summary, users, events


def test_valid_presigned_and_replay(pipeline):
    client, engine = pipeline
    content = (HEADER + VALID).encode()
    batch_id, key = upload(pipeline, content)
    assert process_object(Settings.from_env().bucket, key) == "processed"
    assert process_object(Settings.from_env().bucket, key) == "already_complete"
    status, total, accepted, rejected, _, users, events = inspect_batch(engine, batch_id)
    assert (status, total, accepted, rejected) == ("processed", 1, 1, 0)
    assert users[0].monthly_income == Decimal("1234.56")
    assert users[0].income_currency is None
    assert users[0].employment_status_raw == "Salaried"
    assert len(events) == 1 and events[0].payload == {"batch_id": str(batch_id)}
    assert client.get(f"/uploads/{batch_id}").json()["accepted_rows"] == 1


def test_browser_cors_is_single_origin(pipeline):
    client, _ = pipeline
    origin = os.environ["FRONTEND_ORIGIN"]
    allowed = client.options("/uploads", headers={
        "Origin": origin, "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type,idempotency-key",
    })
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == origin
    denied = client.options("/uploads", headers={
        "Origin": "https://untrusted.example", "Access-Control-Request-Method": "POST",
    })
    assert denied.status_code == 400
    assert "access-control-allow-origin" not in denied.headers
    cors = s3_client(Settings.from_env()).get_bucket_cors(Bucket=Settings.from_env().bucket)
    assert cors["CORSRules"][0]["AllowedOrigins"] == [origin]


def test_local_s3_bridge_uses_existing_ingestion_handler(pipeline, monkeypatch):
    _, engine = pipeline
    batch_id, _ = upload(pipeline, (HEADER + VALID).encode())
    monkeypatch.setattr(local_ingestion_bridge, "make_engine", lambda: engine)
    assert local_ingestion_bridge.scan_once() >= 1
    status, _, accepted, _, _, users, events = inspect_batch(engine, batch_id)
    assert status == "processed" and accepted == 1 and len(users) == len(events) == 1
    assert local_ingestion_bridge.scan_once() == 0


def test_api_gateway_jwt_subject_owns_batch(pipeline, monkeypatch):
    """The AWS adapter reads verified gateway context, not a spoofable HTTP header."""
    _, engine = pipeline
    from apps.api.aws_handler import handler

    monkeypatch.setenv("DEPLOYMENT_MODE", "aws")

    def event(method: str, path: str, subject: str | None, body: dict | None = None) -> dict:
        context: dict = {"http": {"method": method, "path": path, "sourceIp": "127.0.0.1",
                                 "userAgent": "contract-test"}}
        if subject is not None:
            context["authorizer"] = {"jwt": {"claims": {"sub": subject}}}
        return {"version": "2.0", "routeKey": f"{method} {path}", "rawPath": path,
                "rawQueryString": "", "headers": {"host": "example.test", "content-type": "application/json",
                "idempotency-key": "same-key-for-two-users", "x-subject": "spoofed"},
                "requestContext": context, "isBase64Encoded": False,
                "body": json.dumps(body) if body is not None else ""}

    metadata = {"filename": "users.csv", "size_bytes": 100, "content_type": "text/csv"}
    first = handler(event("POST", "/uploads", "subject-a", metadata), {})
    assert first["statusCode"] == 201
    batch_id = json.loads(first["body"])["batch_id"]
    with session_scope(engine) as session:
        assert session.get(UploadBatch, uuid.UUID(batch_id)).owner_subject == "subject-a"
    own = handler(event("GET", f"/uploads/{batch_id}", "subject-a"), {})
    other = handler(event("GET", f"/uploads/{batch_id}", "subject-b"), {})
    errors = handler(event("GET", f"/uploads/{batch_id}/errors", "subject-b"), {})
    missing = handler(event("GET", f"/uploads/{batch_id}", None), {})
    assert own["statusCode"] == 200
    assert other["statusCode"] == errors["statusCode"] == 404
    assert missing["statusCode"] == 401
    second = handler(event("POST", "/uploads", "subject-b", metadata), {})
    assert second["statusCode"] == 201
    assert json.loads(second["body"])["batch_id"] != batch_id
    monkeypatch.setenv("ALLOW_SYNTHETIC_DEMO", "1")
    synthetic = handler(event("POST", "/uploads", "subject-a", {**metadata, "demo_mode": True}), {})
    assert synthetic["statusCode"] == 403


@pytest.mark.parametrize(("content", "expected", "accepted", "rejected", "code"), [
    (HEADER + VALID + "bad,not-email,-1,2000,Other,200\n", "processed_with_errors", 1, 1, "invalid_email"),
    (HEADER + "bad,not-email,-1,2000,Other,200\n", "rejected", 0, 1, "invalid_email"),
    (HEADER + VALID + VALID, "processed_with_errors", 1, 1, "duplicate_user_id"),
    (HEADER + "\n", "rejected", 0, 1, "empty_row"),
])
def test_row_validation(pipeline, content, expected, accepted, rejected, code):
    client, engine = pipeline
    batch_id, key = upload(pipeline, content.encode())
    process_object(Settings.from_env().bucket, key)
    status, _, got_accepted, got_rejected, errors, users, events = inspect_batch(engine, batch_id)
    assert (status, got_accepted, got_rejected) == (expected, accepted, rejected)
    assert code in [entry for sample in errors["samples"] for entry in sample["codes"]]
    assert len(users) == accepted and len(events) == (1 if accepted else 0)
    page = client.get(f"/uploads/{batch_id}/errors").json()["errors"]
    assert len(page) == rejected and code in page[0]["codes"]
    with session_scope(engine) as session:
        assert session.scalar(select(func.count()).select_from(UploadRowError).where(UploadRowError.upload_batch_id == batch_id)) == rejected


@pytest.mark.parametrize(("content", "code"), [
    (b"", "empty_file"),
    (b"user_id,email\none,one@example.com\n", "invalid_headers"),
    ((HEADER + VALID).encode() + b"\xff", "invalid_utf8"),
    ((HEADER + 'one,"unterminated\n').encode(), "malformed_csv"),
    (HEADER.encode(), "no_data_rows"),
    (b"user_id,email,monthly_income,credit_score,employment_status,age,extra\n", "invalid_headers"),
])
def test_file_rejection(pipeline, content, code):
    _, engine = pipeline
    batch_id, key = upload(pipeline, content)
    assert process_object(Settings.from_env().bucket, key) == "rejected"
    status, _, _, _, error, users, events = inspect_batch(engine, batch_id)
    assert status == "rejected" and error["code"] == code
    assert not users and not events


def test_api_metadata_idempotency_and_size(pipeline):
    client, _ = pipeline
    headers = {"Idempotency-Key": str(uuid.uuid4())}
    metadata = {"filename": "users.csv", "size_bytes": 100, "content_type": "text/csv"}
    first = client.post("/uploads", headers=headers, json=metadata)
    replay = client.post("/uploads", headers=headers, json=metadata)
    assert first.status_code == replay.status_code == 201
    assert first.json()["batch_id"] == replay.json()["batch_id"]
    assert client.post("/uploads", headers=headers, json={**metadata, "size_bytes": 101}).status_code == 409
    assert client.post("/uploads", headers={"Idempotency-Key": str(uuid.uuid4())}, json={
        **metadata, "size_bytes": Settings.from_env().max_bytes + 1,
    }).status_code == 413
    assert client.post("/uploads", headers={"Idempotency-Key": str(uuid.uuid4())}, json={
        **metadata, "filename": "../users.csv",
    }).status_code == 422
    assert client.get(f"/uploads/{uuid.uuid4()}").status_code == 404
    assert client.get("/health").json() == {"status": "ok"}


def test_oversized_object(pipeline, monkeypatch):
    _, engine = pipeline
    batch_id, key = upload(pipeline, (HEADER + VALID).encode())
    monkeypatch.setenv("CSV_MAX_BYTES", "10")
    assert process_object(Settings.from_env().bucket, key) == "rejected"
    assert inspect_batch(engine, batch_id)[4]["code"] == "file_too_large"


def test_concurrent_attempts_single_completion(pipeline):
    _, engine = pipeline
    batch_id, key = upload(pipeline, (HEADER + VALID).encode())
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: process_object(Settings.from_env().bucket, key), range(2)))
    assert "processed" in results
    assert set(results) <= {"processed", "already_processing", "already_complete"}
    assert len(inspect_batch(engine, batch_id)[6]) == 1


def test_ten_thousand_rows_chunked(pipeline):
    _, engine = pipeline
    rows = [f"load-{number},load{number}@example.com,25000.01,700,Business,30\n"
            for number in range(10_000)]
    batch_id, key = upload(pipeline, (HEADER + "".join(rows)).encode())
    assert process_object(Settings.from_env().bucket, key) == "processed"
    status, total, accepted, rejected, _, users, events = inspect_batch(engine, batch_id)
    assert (status, total, accepted, rejected) == ("processed", 10_000, 10_000, 0)
    assert len(users) == 10_000 and len(events) == 1
    assert all(user.employment_status == "other" for user in users)


def test_rollback_then_retry(pipeline, monkeypatch):
    _, engine = pipeline
    batch_id, key = upload(pipeline, (HEADER + VALID).encode())
    original = worker_module.parse_csv

    def fail_after_insert(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(worker_module, "parse_csv", fail_after_insert)
    with pytest.raises(RuntimeError, match="^ingestion_failed$"):
        process_object(Settings.from_env().bucket, key)
    assert inspect_batch(engine, batch_id)[0] == "failed"
    assert not inspect_batch(engine, batch_id)[5:7][0]
    monkeypatch.setattr(worker_module, "parse_csv", original)
    assert process_object(Settings.from_env().bucket, key) == "processed"
    assert len(inspect_batch(engine, batch_id)[5]) == 1


def test_unknown_employment_is_preserved_but_not_recognized():
    item, errors = validate_row({"user_id": "x", "email": "x@example.com", "monthly_income": "1.00",
                                 "credit_score": "700", "employment_status": "Business", "age": "30"})
    assert errors == []
    assert item["employment_status"] == "other" and item["employment_status_raw"] == "Business"


def test_sensitive_values_not_logged(pipeline, caplog):
    _, key = upload(pipeline, (HEADER + "private-id,secret@example.com,1,700,Salaried,30\n").encode())
    process_object(Settings.from_env().bucket, key)
    assert "secret@example.com" not in caplog.text and "private-id" not in caplog.text


def test_event_validation(pipeline):
    with pytest.raises(ValueError):
        lambda_handler({"Records": [{"eventName": "ObjectRemoved:Delete"}]}, None)
    with pytest.raises(ValueError):
        process_object(Settings.from_env().bucket, "uploads/unknown/file.csv")


def test_stream_limit_and_decimal_precision():
    class Body:
        def __init__(self, data):
            self.data = data

        def read(self, count):
            chunk, self.data = self.data[:count], self.data[count:]
            return chunk

    stream = LimitedStream(Body(b"12345"), 4)
    target = bytearray(8)
    with pytest.raises(FileRejected):
        stream.readinto(target)
    row = {"user_id": "x", "email": "x@example.com", "monthly_income": "1.001",
           "credit_score": "700", "employment_status": "Salaried", "age": "30"}
    _, errors = validate_row(row)
    assert errors == ["invalid_monthly_income"]
