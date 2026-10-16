"""The private notification helper must receive the scoped SES gate, not just its mode."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "infrastructure/docker-compose.yml"
SCOPED = (
    "NOTIFICATION_SES_AUTHORIZED_BATCH_ID",
    "NOTIFICATION_SES_AUTHORIZED_IDEMPOTENCY_KEY",
)


def test_scoped_ses_values_have_fail_closed_compose_defaults() -> None:
    services = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]
    helper = services["discovery"]["environment"]
    for name in SCOPED:
        assert helper[name] == "${" + name + ":-}"
    assert helper["NOTIFICATION_TRANSPORT"] == "${NOTIFICATION_TRANSPORT:-mock}"
    assert helper["NOTIFICATION_SES_ENABLED"] == "${NOTIFICATION_SES_ENABLED:-0}"
    assert helper["NOTIFICATION_SES_MAX_ATTEMPTS"] == "${NOTIFICATION_SES_MAX_ATTEMPTS:-0}"
    assert all(name not in services["n8n"]["environment"] for name in SCOPED)


def test_compose_interpolates_both_scoped_values_without_running_services() -> None:
    if not shutil.which("docker") or not (ROOT / ".env").exists():
        pytest.skip("Docker and a local ignored .env are required for interpolation verification")
    batch = str(uuid.uuid4())
    key = "a" * 64  # Synthetic test value, never a live authorization.
    env = {**os.environ, SCOPED[0]: batch, SCOPED[1]: key,
           "NOTIFICATION_TRANSPORT": "mock", "NOTIFICATION_SES_ENABLED": "0",
           "NOTIFICATION_SES_MAX_ATTEMPTS": "0"}
    result = subprocess.run(
        ["docker", "compose", "--project-directory", str(ROOT), "--env-file", str(ROOT / ".env"),
         "-f", str(COMPOSE), "config", "--format", "json"],
        env=env, capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, "Docker Compose configuration failed"
    helper = json.loads(result.stdout)["services"]["discovery"]["environment"]
    assert helper[SCOPED[0]] == batch
    assert helper[SCOPED[1]] == key
    assert (helper["NOTIFICATION_TRANSPORT"], helper["NOTIFICATION_SES_ENABLED"],
            helper["NOTIFICATION_SES_MAX_ATTEMPTS"]) == ("mock", "0", "0")
