"""Idempotently initialize the local S3-compatible bucket."""

import os
import sys
from typing import Any

from botocore.exceptions import ClientError

from services.ingestion.config import Settings, s3_client


def ensure_bucket() -> None:
    settings = Settings.from_env()
    client = s3_client(settings)
    try:
        client.head_bucket(Bucket=settings.bucket)
    except ClientError as error:
        if error.response["ResponseMetadata"]["HTTPStatusCode"] != 404:
            raise
        kwargs: dict[str, Any] = {"Bucket": settings.bucket}
        if settings.region != "us-east-1":
            kwargs["CreateBucketConfiguration"] = {"LocationConstraint": settings.region}
        client.create_bucket(**kwargs)
    origin = os.environ.get("FRONTEND_ORIGIN", "http://localhost:3000")
    if not origin.startswith(("http://localhost:", "http://127.0.0.1:")):
        raise ValueError("local S3 CORS origin must be loopback")
    client.put_bucket_cors(Bucket=settings.bucket, CORSConfiguration={"CORSRules": [{
        "AllowedOrigins": [origin], "AllowedMethods": ["POST", "GET", "HEAD"],
        "AllowedHeaders": ["Content-Type"], "ExposeHeaders": ["ETag"],
        "MaxAgeSeconds": 300,
    }]})
    print("Local S3 bucket ready.")


if __name__ == "__main__":
    if sys.argv[1:] != ["init"]:
        raise SystemExit("usage: python -m scripts.local_s3 init")
    ensure_bucket()
