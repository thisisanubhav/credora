"""LocalStack-only S3 event bridge; production uses native S3→Lambda notification."""

from __future__ import annotations

import sys
import time

from botocore.exceptions import ClientError
from sqlalchemy import select

from services.common.db import make_engine, session_scope
from services.common.models import UploadBatch
from services.ingestion.config import Settings, s3_client
from services.ingestion.worker import lambda_handler


def scan_once() -> int:
    settings = Settings.from_env()
    if settings.endpoint_url is None or not settings.endpoint_url.startswith((
        "http://127.0.0.1:", "http://localhost:",
    )):
        raise ValueError("local bridge requires loopback S3 emulator")
    engine = make_engine()
    try:
        with session_scope(engine) as session:
            pending = session.execute(select(UploadBatch.object_bucket, UploadBatch.object_key).where(
                UploadBatch.status == "uploaded").order_by(UploadBatch.created_at).limit(100)).all()
        client = s3_client(settings)
        processed = 0
        for bucket, key in pending:
            try:
                metadata = client.head_object(Bucket=bucket, Key=key)
            except ClientError as error:
                if error.response.get("ResponseMetadata", {}).get("HTTPStatusCode") == 404:
                    continue
                raise
            event = {"Records": [{"eventName": "ObjectCreated:Post", "s3": {
                "bucket": {"name": bucket}, "object": {"key": key,
                "eTag": str(metadata["ETag"]).strip('"')}}}]}
            outcome = lambda_handler(event, None)
            if outcome["results"] == ["processed"]:
                processed += 1
        return processed
    finally:
        engine.dispose()


def main() -> None:
    if sys.argv[1:] not in (["--once"], ["--watch"]):
        raise SystemExit("usage: python -m scripts.local_ingestion_bridge {--once|--watch}")
    while True:
        count = scan_once()
        if count:
            print(f"Local S3 event bridge processed {count} batch(es).")
        if sys.argv[1] == "--once":
            break
        time.sleep(2)


if __name__ == "__main__":
    main()
