"""Validated ingestion configuration; secrets remain in environment/IAM."""

from __future__ import annotations

import os
from dataclasses import dataclass

import boto3
from botocore.config import Config


@dataclass(frozen=True)
class Settings:
    bucket: str
    max_bytes: int
    chunk_size: int
    url_ttl_seconds: int
    lease_seconds: int
    endpoint_url: str | None
    region: str

    @classmethod
    def from_env(cls) -> Settings:
        def positive(name: str, default: int, maximum: int) -> int:
            value = int(os.getenv(name, str(default)))
            if not 1 <= value <= maximum:
                raise ValueError(f"{name} must be between 1 and {maximum}")
            return value

        bucket = os.getenv("S3_BUCKET", "")
        if not bucket or len(bucket) > 63:
            raise ValueError("S3_BUCKET is required")
        return cls(
            bucket=bucket,
            max_bytes=positive("CSV_MAX_BYTES", 10_000_000, 100_000_000),
            chunk_size=positive("CSV_CHUNK_SIZE", 500, 10_000),
            url_ttl_seconds=positive("UPLOAD_URL_TTL_SECONDS", 600, 3600),
            lease_seconds=positive("INGESTION_LEASE_SECONDS", 900, 3600),
            endpoint_url=os.getenv("S3_ENDPOINT_URL") or None,
            region=os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1",
        )


def s3_client(settings: Settings):  # type: ignore[no-untyped-def]
    return boto3.client(
        "s3",
        endpoint_url=settings.endpoint_url,
        region_name=settings.region,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )
