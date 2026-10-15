"""Offline AWS contracts; no AWS SDK client or deploy command is used here."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.aws_validate import validate_prerequisites, validate_template
from services.common.db import database_url
from services.ingestion import worker


def test_serverless_security_and_handlers() -> None:
    template = validate_template()
    assert template["provider"]["vpc"]["subnetIds"] == [
        "${env:PRIVATE_SUBNET_A_ID}", "${env:PRIVATE_SUBNET_B_ID}",
    ]
    assert template["provider"]["environment"]["POSTGRES_HOST"] == "${env:DB_HOST}"


def test_aws_prerequisite_guard() -> None:
    values = {
        "AWS_REGION": "us-east-1", "FRONTEND_ORIGIN": "https://upload.example.test",
        "JWT_ISSUER_URL": "https://issuer.example.test", "JWT_AUDIENCE": "loan-demo",
        "UPLOAD_BUCKET_NAME": "loan-demo-dev-123456789012", "PRIVATE_SUBNET_A_ID": "subnet-a",
        "PRIVATE_SUBNET_B_ID": "subnet-b", "LAMBDA_SECURITY_GROUP_ID": "sg-lambda",
        "DB_HOST": "private-db.example.test", "DB_NAME": "loan_engine",
        "DB_RUNTIME_USER": "loan_engine_runtime",
        "DB_SECRET_ARN": "arn:aws:secretsmanager:us-east-1:123456789012:secret:loan-db",
    }
    validate_prerequisites(values)
    with pytest.raises(ValueError, match="HTTPS"):
        validate_prerequisites({**values, "FRONTEND_ORIGIN": "http://localhost:3107"})
    with pytest.raises(ValueError, match="private RDS"):
        validate_prerequisites({**values, "DB_HOST": "postgres"})
    with pytest.raises(ValueError, match="different private subnets"):
        validate_prerequisites({**values, "PRIVATE_SUBNET_B_ID": "subnet-a"})


def test_native_s3_event_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[str, str, str | None]] = []
    def capture(bucket: str, key: str, event_etag: str | None = None) -> str:
        seen.append((bucket, key, event_etag))
        return "processed"

    monkeypatch.setattr(worker, "process_object", capture)
    event = {"Records": [{"eventName": "ObjectCreated:Post", "s3": {
        "bucket": {"name": "loan-demo"},
        "object": {"key": "uploads%2Fbatch%2Ffile.csv", "eTag": "etag"},
    }}]}
    assert worker.lambda_handler(event, None) == {"results": ["processed"]}
    assert seen == [("loan-demo", "uploads/batch/file.csv", "etag")]
    with pytest.raises(ValueError, match="ObjectCreated"):
        worker.lambda_handler({"Records": [{"eventName": "ObjectRemoved:Delete"}]}, None)


def test_runtime_rds_url_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_HOST", "private-db.example.test")
    monkeypatch.setenv("POSTGRES_PORT", "5432")
    monkeypatch.setenv("POSTGRES_DB", "loan_engine")
    monkeypatch.setenv("APP_DB_USER", "runtime")
    monkeypatch.setenv("APP_DB_PASSWORD", "test-only-not-a-real-credential")
    url = database_url()
    assert url.host == "private-db.example.test" and url.username == "runtime"
    assert "test-only-not-a-real-credential" not in str(url)
    monkeypatch.setenv("DEPLOYMENT_MODE", "aws")
    assert database_url().query["sslmode"] == "require"


def test_no_cloud_deploy_shortcut() -> None:
    makefile = (Path(__file__).resolve().parents[2] / "Makefile").read_text(encoding="utf-8")
    assert "serverless deploy" not in makefile
