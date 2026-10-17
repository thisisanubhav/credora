"""Exercise the proposed diagnostic overlay offline; never execute a live workflow."""
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("code", ["MessageRejected", "InvalidParameterValue", "SignatureDoesNotMatch"])
def test_pinned_diagnostics_preserve_only_allowlisted_fields(code: str) -> None:
    result = subprocess.run([
        "docker", "run", "--rm", "--network", "none", "--read-only",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "-v", f"{ROOT}:/audit:ro", "--entrypoint", "node", "n8nio/n8n:2.43.5",
        "/audit/tests/notifications/ses_diagnostics_capture.cjs", "versioned", code,
    ], capture_output=True, text=True, check=True, timeout=30)
    captured = json.loads(result.stdout)
    assert captured["nodeOutput"]["ses_diagnostics"]["aws_error_code"] == code
    assert captured["signatureVerified"] is True
