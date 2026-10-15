"""Measure the real M3 CSV parser on the assignment sample in a guarded test DB."""

from __future__ import annotations

import io
import os
import resource
import time
import uuid

import httpx
from alembic import command
from alembic.config import Config
from sqlalchemy import event

from scripts.db_admin import test_database
from services.common.db import make_engine, session_scope
from services.common.models import UploadBatch
from services.ingestion import worker

SAMPLE_URL = "https://drive.google.com/uc?export=download&id=1KBaZRkfr7T2kVBKSr_2fr7v2tTe6f8qu"


def main() -> None:
    name = os.environ["TEST_DB_NAME"].removesuffix("_test") + "_qa_ingestion_test"
    if not name.endswith("_test") or name in {os.environ["POSTGRES_DB"], os.environ["N8N_DB_NAME"]}:
        raise ValueError("unsafe ingestion benchmark database")
    with httpx.Client(follow_redirects=True, timeout=30) as client:
        response = client.get(SAMPLE_URL)
        response.raise_for_status()
        content = response.content
    if not 100_000 < len(content) < 1_500_000:
        raise ValueError("assignment CSV size outside reviewed benchmark envelope")
    previous_test = os.environ["TEST_DB_NAME"]
    previous_database = os.environ.get("DATABASE_NAME")
    os.environ["TEST_DB_NAME"] = name
    os.environ["DATABASE_NAME"] = name
    try:
        test_database()
        command.upgrade(Config("database/alembic.ini"), "head")
        engine = make_engine(role="migration", database=name)
        original_validate = worker.validate_row
        validation_seconds = 0.0
        insert_seconds = 0.0
        cursor_started = 0.0

        def timed_validate(row: dict[str, str]):  # type: ignore[no-untyped-def]
            nonlocal validation_seconds
            start = time.perf_counter()
            try:
                return original_validate(row)
            finally:
                validation_seconds += time.perf_counter() - start

        def before_cursor(conn, cursor, statement, parameters, context, executemany):  # type: ignore[no-untyped-def]
            nonlocal cursor_started
            cursor_started = time.perf_counter()

        def after_cursor(conn, cursor, statement, parameters, context, executemany):  # type: ignore[no-untyped-def]
            nonlocal insert_seconds
            if statement.lstrip().upper().startswith("INSERT"):
                insert_seconds += time.perf_counter() - cursor_started

        worker.validate_row = timed_validate
        event.listen(engine, "before_cursor_execute", before_cursor)
        event.listen(engine, "after_cursor_execute", after_cursor)
        batch_id = uuid.uuid4()
        try:
            start = time.perf_counter()
            with session_scope(engine) as session:
                session.add(UploadBatch(
                    id=batch_id, object_bucket="qa-benchmark",
                    object_key=f"qa-benchmark/{batch_id}.csv", schema_version=1,
                    status="processing",
                ))
                session.flush()
                total, accepted, errors = worker.parse_csv(
                    io.BytesIO(content), max_bytes=1_500_000, chunk_size=500,
                    session=session, batch_id=batch_id,
                )
            elapsed = time.perf_counter() - start
        finally:
            worker.validate_row = original_validate
            engine.dispose()
        if (total, accepted, len(errors)) != (10_000, 10_000, 0):
            raise ValueError("sample ingestion result changed")
        print({
            "sample_rows": total, "sample_bytes": len(content), "accepted": accepted,
            "parse_and_commit_seconds": round(elapsed, 3),
            "validation_seconds_instrumented": round(validation_seconds, 3),
            "sql_insert_seconds_instrumented": round(insert_seconds, 3),
            "rows_per_second_parse_and_commit": round(total / elapsed, 1),
            "peak_process_rss_raw": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "database": name, "batch_id": str(batch_id),
        })
    finally:
        os.environ["TEST_DB_NAME"] = previous_test
        if previous_database is None:
            os.environ.pop("DATABASE_NAME", None)
        else:
            os.environ["DATABASE_NAME"] = previous_database


if __name__ == "__main__":
    main()
