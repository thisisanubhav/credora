"""Offline M8 template and prerequisite checks; never instantiates an AWS client."""

from __future__ import annotations

import importlib
import os
import re
import sys
from pathlib import Path
from zipfile import ZipFile

import yaml

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "infrastructure" / "serverless.yml"
ARTIFACT = ROOT / ".build" / "m8" / "lambda.zip"


def validate_template(*, require_artifact: bool = False) -> dict:
    document = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
    assert document["frameworkVersion"] == "4.44.0"
    provider = document["provider"]
    assert provider["runtime"] == "python3.12" and provider["architecture"] == "x86_64"
    assert provider["httpApi"]["payload"] == "2.0"
    assert provider["httpApi"]["cors"]["allowedOrigins"] == ["${env:FRONTEND_ORIGIN}"]
    assert "*" not in provider["httpApi"]["cors"]["allowedOrigins"]
    assert provider["environment"]["DEPLOYMENT_MODE"] == "aws"
    assert provider["environment"]["APP_DB_PASSWORD"].startswith("{{resolve:secretsmanager:")
    assert "S3_ENDPOINT_URL" not in provider["environment"]
    authorizers = provider["httpApi"]["authorizers"]
    assert "uploadJwt" in authorizers and authorizers["uploadJwt"]["audience"]
    functions = document["functions"]
    assert functions["uploadApi"]["handler"] == "apps.api.aws_handler.handler"
    assert functions["ingestion"]["handler"] == "services.ingestion.worker.lambda_handler"
    for route in functions["uploadApi"]["events"]:
        spec = route["httpApi"]
        if spec["path"] != "/health":
            assert spec["authorizer"]["name"] == "uploadJwt"
    assert functions["uploadApi"]["role"] != functions["ingestion"]["role"]
    assert functions["ingestion"]["reservedConcurrency"] <= 2
    resources = document["resources"]["Resources"]
    bucket = resources["UploadBucket"]["Properties"]
    assert all(bucket["PublicAccessBlockConfiguration"].values())
    assert bucket["BucketEncryption"]["ServerSideEncryptionConfiguration"][0][
        "ServerSideEncryptionByDefault"]["SSEAlgorithm"] == "AES256"
    assert bucket["NotificationConfiguration"]["LambdaConfigurations"][0]["Event"] == "s3:ObjectCreated:*"
    rules = bucket["NotificationConfiguration"]["LambdaConfigurations"][0]["Filter"]["S3Key"]["Rules"]
    assert rules == [{"Name": "prefix", "Value": "uploads/"}, {"Name": "suffix", "Value": ".csv"}]
    assert bucket["CorsConfiguration"]["CorsRules"][0]["AllowedOrigins"] == ["${env:FRONTEND_ORIGIN}"]
    assert resources["IngestionFailureDestination"]["Properties"]["DestinationConfig"]["OnFailure"]
    assert resources["IngestionS3InvokePermission"]["Properties"]["SourceAccount"]
    assert resources["UploadBucketPolicy"]["Properties"]["PolicyDocument"]["Statement"][0][
        "Condition"]["Bool"]["aws:SecureTransport"] == "false"
    forbidden = {"AWS::RDS::DBInstance", "AWS::EC2::NatGateway", "AWS::EC2::Instance"}
    assert not forbidden.intersection(resource["Type"] for resource in resources.values())
    api_actions = resources["ApiExecutionRole"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"]
    worker_actions = resources["IngestionExecutionRole"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"]
    assert [item["Action"] for item in api_actions] == ["s3:PutObject"]
    assert {item["Action"] for item in worker_actions} == {"s3:GetObject", "sqs:SendMessage"}
    for handler in ("apps.api.aws_handler", "services.ingestion.worker"):
        importlib.import_module(handler)
    if require_artifact:
        assert ARTIFACT.is_file(), "run `make aws-package-local` first"
        with ZipFile(ARTIFACT) as archive:
            names = set(archive.namelist())
            assert "apps/api/aws_handler.py" in names and "services/ingestion/worker.py" in names
            assert any(name.startswith("psycopg_binary-") for name in names)
    return document


def validate_prerequisites(values: dict[str, str]) -> None:
    required = (
        "AWS_REGION", "FRONTEND_ORIGIN", "JWT_ISSUER_URL", "JWT_AUDIENCE",
        "UPLOAD_BUCKET_NAME", "PRIVATE_SUBNET_A_ID", "PRIVATE_SUBNET_B_ID",
        "LAMBDA_SECURITY_GROUP_ID", "DB_HOST", "DB_NAME", "DB_RUNTIME_USER", "DB_SECRET_ARN",
    )
    missing = [key for key in required if not values.get(key)]
    if missing:
        raise ValueError("missing deployment prerequisites: " + ", ".join(missing))
    if not values["FRONTEND_ORIGIN"].startswith("https://"):
        raise ValueError("cloud frontend origin must be HTTPS")
    if not values["JWT_ISSUER_URL"].startswith("https://"):
        raise ValueError("JWT issuer must be HTTPS")
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{2,62}", values["UPLOAD_BUCKET_NAME"]):
        raise ValueError("invalid upload bucket name")
    if values["DB_HOST"] in {"localhost", "127.0.0.1", "postgres"}:
        raise ValueError("AWS deployment needs a private RDS hostname")
    if values["PRIVATE_SUBNET_A_ID"] == values["PRIVATE_SUBNET_B_ID"]:
        raise ValueError("two different private subnets are required")
    if not values["DB_SECRET_ARN"].startswith("arn:aws:secretsmanager:"):
        raise ValueError("DB_SECRET_ARN must reference Secrets Manager")


def main() -> None:
    option = sys.argv[1:]
    if option not in ([], ["--package"], ["--preflight"]):
        raise SystemExit("usage: python -m scripts.aws_validate [--package|--preflight]")
    validate_template(require_artifact=option == ["--package"])
    if option == ["--preflight"]:
        validate_prerequisites(dict(os.environ))
    print("PASS: offline AWS template/handler checks" + (" and local artifact" if option == ["--package"] else ""))


if __name__ == "__main__":
    main()
