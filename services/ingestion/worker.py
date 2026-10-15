"""S3 ObjectCreated worker: streaming parse, one atomic user/outbox transaction."""

from __future__ import annotations

import csv
import io
import re
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import unquote_plus

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import insert, select, update

from services.common.db import make_engine, session_scope
from services.common.models import OutboxEvent, UploadBatch, UploadRowError, User
from services.ingestion.config import Settings, s3_client

REQUIRED = ("user_id", "email", "monthly_income", "credit_score", "employment_status", "age")
ALLOWED = set(REQUIRED) | {"name"}
EMPLOYMENT = {"salaried": "salaried", "self-employed": "self_employed", "self_employed": "self_employed"}
MAX_ERROR_SAMPLES = 100


class FileRejected(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class LimitedStream(io.RawIOBase):
    """Adapt S3 StreamingBody to TextIOWrapper with a strict byte ceiling."""

    def __init__(self, body: Any, limit: int):
        self.body = body
        self.limit = limit
        self.consumed = 0

    def readable(self) -> bool:
        return True

    def readinto(self, target: Any) -> int:
        data = self.body.read(min(len(target), self.limit - self.consumed + 1))
        self.consumed += len(data)
        if self.consumed > self.limit:
            raise FileRejected("file_too_large")
        target[:len(data)] = data
        return len(data)


def validate_row(row: dict[str, str]) -> tuple[dict[str, Any] | None, list[str]]:
    errors: list[str] = []
    source_id = row["user_id"].strip()
    if not 1 <= len(source_id) <= 128:
        errors.append("invalid_user_id")
    try:
        email = validate_email(row["email"].strip(), check_deliverability=False).normalized.lower()
        if len(email) > 320:
            raise ValueError
    except (EmailNotValidError, ValueError):
        email = ""
        errors.append("invalid_email")
    try:
        income = Decimal(row["monthly_income"].strip())
        exponent = income.as_tuple().exponent
        if not income.is_finite() or income < 0 or income > Decimal("999999999999.99") or not isinstance(exponent, int) or exponent < -2:
            raise ValueError
    except (InvalidOperation, ValueError):
        income = Decimal(0)
        errors.append("invalid_monthly_income")

    def bounded_integer(field: str, maximum: int) -> int:
        raw = row[field].strip()
        if not re.fullmatch(r"[0-9]+", raw) or len(raw) > 4 or int(raw) > maximum:
            errors.append(f"invalid_{field}")
            return 0
        return int(raw)

    score = bounded_integer("credit_score", 1000)
    age = bounded_integer("age", 130)
    raw_employment = row["employment_status"].strip()
    if not 1 <= len(raw_employment) <= 128:
        errors.append("invalid_employment_status")
    normalized = EMPLOYMENT.get(raw_employment.casefold(), "other")
    if errors:
        return None, errors
    return {
        "id": uuid.uuid4(), "source_user_id": source_id, "email": email,
        "monthly_income": income, "income_currency": None,
        "credit_score": score, "age": age,
        "employment_status": normalized, "employment_status_raw": raw_employment,
    }, []


def parse_csv(body: Any, *, max_bytes: int, chunk_size: int, session: Any, batch_id: uuid.UUID) -> tuple[int, int, list[dict[str, Any]]]:
    """Stream without retaining full CSV; all inserts remain uncommitted until completion."""
    try:
        text_stream = io.TextIOWrapper(io.BufferedReader(LimitedStream(body, max_bytes)), encoding="utf-8-sig", newline="")
        reader = csv.reader(text_stream, strict=True)
        header = next(reader, None)
        if header is None:
            raise FileRejected("empty_file")
        if len(header) != len(set(header)) or not set(REQUIRED).issubset(header) or set(header) - ALLOWED:
            raise FileRejected("invalid_headers")
        total = accepted = 0
        errors: list[dict[str, Any]] = []
        seen: set[str] = set()
        pending: list[dict[str, Any]] = []
        pending_errors: list[dict[str, Any]] = []
        for values in reader:
            total += 1
            row_number = reader.line_num
            if not any(value.strip() for value in values):
                item, codes = None, ["empty_row"]
            elif len(values) != len(header):
                item, codes = None, ["invalid_column_count"]
            else:
                item, codes = validate_row(dict(zip(header, values, strict=True)))
                if item is not None:
                    if item["source_user_id"] in seen:
                        item, codes = None, ["duplicate_user_id"]
                    else:
                        seen.add(item["source_user_id"])
            if item is None:
                pending_errors.append({"id": uuid.uuid4(), "upload_batch_id": batch_id,
                                       "row_number": row_number, "codes": codes})
                if len(pending_errors) >= chunk_size:
                    session.execute(insert(UploadRowError), pending_errors)
                    pending_errors.clear()
                if len(errors) < MAX_ERROR_SAMPLES:
                    errors.append({"row": row_number, "codes": codes})
            else:
                item["upload_batch_id"] = batch_id
                pending.append(item)
                accepted += 1
                if len(pending) >= chunk_size:
                    session.execute(insert(User), pending)
                    pending.clear()
        if pending:
            session.execute(insert(User), pending)
        if pending_errors:
            session.execute(insert(UploadRowError), pending_errors)
        if total == 0:
            raise FileRejected("no_data_rows")
        return total, accepted, errors
    except UnicodeDecodeError as error:
        raise FileRejected("invalid_utf8") from error
    except csv.Error as error:
        raise FileRejected("malformed_csv") from error


def _claim(engine: Any, batch_id: uuid.UUID, settings: Settings) -> uuid.UUID | None:
    token = uuid.uuid4()
    now = datetime.now(UTC)
    with session_scope(engine) as session:
        claimed = session.execute(
            update(UploadBatch).where(
                UploadBatch.id == batch_id,
                (UploadBatch.status.in_(["uploaded", "failed"])) |
                ((UploadBatch.status == "processing") & (UploadBatch.processing_lease_expires_at < now)),
            ).values(status="processing", processing_started_at=now, processing_token=token,
                     processing_lease_expires_at=now + timedelta(seconds=settings.lease_seconds),
                     updated_at=now).returning(UploadBatch.id)
        ).scalar_one_or_none()
    return token if claimed else None


def _set_failure(engine: Any, batch_id: uuid.UUID, token: uuid.UUID, status: str, code: str) -> None:
    with session_scope(engine) as session:
        session.execute(update(UploadBatch).where(
            UploadBatch.id == batch_id, UploadBatch.processing_token == token,
        ).values(status=status, processing_token=None, processing_lease_expires_at=None,
                 error_summary={"code": code}, updated_at=datetime.now(UTC)))


def process_object(bucket: str, key: str, *, event_etag: str | None = None) -> str:
    settings = Settings.from_env()
    if bucket != settings.bucket or not re.fullmatch(r"uploads/[0-9a-f-]{36}/[0-9a-f]{32}\.csv", key):
        raise ValueError("S3 object does not match upload namespace")
    batch_id = uuid.UUID(key.split("/")[1])
    engine = make_engine()
    try:
        with session_scope(engine) as session:
            batch = session.scalar(select(UploadBatch).where(
                UploadBatch.id == batch_id, UploadBatch.object_bucket == bucket,
                UploadBatch.object_key == key,
            ))
            if batch is None:
                raise ValueError("unknown upload batch")
            if batch.status in {"processed", "processed_with_errors", "rejected", "matching", "matched", "match_failed"}:
                return "already_complete"
        token = _claim(engine, batch_id, settings)
        if token is None:
            return "already_processing"
        try:
            s3 = s3_client(settings)
            metadata = s3.head_object(Bucket=bucket, Key=key)
            if metadata["ContentLength"] > settings.max_bytes:
                raise FileRejected("file_too_large")
            etag = metadata.get("ETag", "").strip('"')
            if event_etag and event_etag.strip('"') != etag:
                raise FileRejected("object_changed_after_event")
            obj = s3.get_object(Bucket=bucket, Key=key)
            try:
                if obj.get("ETag", "").strip('"') != etag:
                    raise FileRejected("object_changed_during_processing")
                with session_scope(engine) as session:
                    current = session.execute(select(UploadBatch).where(UploadBatch.id == batch_id).with_for_update()).scalar_one()
                    if current.processing_token != token:
                        return "claim_lost"
                    total, accepted, errors = parse_csv(
                        obj["Body"], max_bytes=settings.max_bytes, chunk_size=settings.chunk_size,
                        session=session, batch_id=batch_id,
                    )
                    current.total_rows = total
                    current.accepted_rows = accepted
                    current.rejected_rows = total - accepted
                    current.error_summary = {"samples": errors, "sample_limit": MAX_ERROR_SAMPLES} if errors else None
                    current.object_etag = etag
                    current.status = "processed" if accepted == total else ("processed_with_errors" if accepted else "rejected")
                    current.processed_at = datetime.now(UTC)
                    current.processing_token = None
                    current.processing_lease_expires_at = None
                    if accepted:
                        session.add(OutboxEvent(
                            event_id=uuid.uuid5(uuid.NAMESPACE_URL, f"upload_batch.ready.v1:{batch_id}"),
                            event_type="upload_batch.ready.v1", aggregate_id=batch_id,
                            payload={"batch_id": str(batch_id)},
                        ))
                return "processed" if accepted else "rejected"
            finally:
                obj["Body"].close()
        except FileRejected as error:
            _set_failure(engine, batch_id, token, "rejected", error.code)
            return "rejected"
        except Exception:  # noqa: BLE001 - sanitize unexpected SDK/DB errors before Lambda logs them
            _set_failure(engine, batch_id, token, "failed", "processing_error")
            # SQLAlchemy exceptions may include bound row values; never leak them
            # into Lambda/runtime logs or API responses.
            raise RuntimeError("ingestion_failed") from None
    finally:
        engine.dispose()


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    results = []
    records = event.get("Records")
    if not isinstance(records, list) or not records:
        raise ValueError("S3 Records are required")
    for record in records:
        if not str(record.get("eventName", "")).startswith("ObjectCreated:"):
            raise ValueError("only S3 ObjectCreated events are accepted")
        object_data = record["s3"]["object"]
        results.append(process_object(
            record["s3"]["bucket"]["name"], unquote_plus(object_data["key"]),
            event_etag=object_data.get("eTag"),
        ))
    return {"results": results}
