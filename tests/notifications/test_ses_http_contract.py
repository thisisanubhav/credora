"""Offline checks of the final n8n 2.43.5 SES HTTP request. No AWS transport."""

from __future__ import annotations

import json
import re
import subprocess
from copy import deepcopy
from pathlib import Path
from urllib.parse import parse_qsl

import pytest

ROOT = Path(__file__).resolve().parents[2]
ALLOWED = {
    "Action", "Version", "Source", "Destination.ToAddresses.member.1",
    "Message.Subject.Data", "Message.Body.Html.Data", "Message.Body.Html.Charset",
}
ADDRESS = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _capture(mode: str) -> dict:
    command = ["docker", "run", "--rm", "--network", "none", "--read-only",
               "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
               "-v", f"{ROOT}:/audit:ro", "--entrypoint", "node", "n8nio/n8n:2.43.5",
               "/audit/tests/notifications/ses_offline_capture.cjs", mode]
    result = subprocess.run(command, capture_output=True, text=True, check=True, timeout=30)
    return json.loads(result.stdout)


def _violations(request: dict) -> list[str]:
    """Strict local gate for this one-recipient, synthetic SES demonstration."""
    errors: list[str] = []
    params = request["params"]
    raw = request["rawQuery"]
    pairs = parse_qsl(raw, keep_blank_values=True)
    keys = [key for key, _ in pairs]
    if len(keys) != len(set(keys)) or dict(pairs) != params:
        errors.append("duplicate_or_inconsistent_query")
    if re.search(r"[\s<>]", raw):
        errors.append("invalid_query_encoding")
    if request["method"] != "POST" or request["host"] != "email.eu-north-1.amazonaws.com" or request["path"] != "/":
        errors.append("endpoint_or_method")
    if request["body"] is not None:
        errors.append("unexpected_body")
    if params.get("Action") != "SendEmail" or params.get("Version") != "2010-12-01":
        errors.append("action_or_version")
    if set(params) != ALLOWED or request["recipientCount"] != 1:
        errors.append("parameter_set_or_recipient_count")
    for field in ("Source", "Destination.ToAddresses.member.1"):
        value = params.get(field)
        if not isinstance(value, str) or not ADDRESS.fullmatch(value) or value.strip() != value:
            errors.append(f"invalid_{field}")
    if params.get("Source") != params.get("Destination.ToAddresses.member.1"):
        errors.append("recipient_isolation")
    for field in ("Message.Subject.Data", "Message.Body.Html.Data"):
        value = params.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"invalid_{field}")
    if params.get("Message.Body.Html.Charset") != "UTF-8":
        errors.append("invalid_charset")
    if request["signatureV4"] is not True or not str(request["authorizationScope"]).endswith("/eu-north-1/ses/aws4_request"):
        errors.append("invalid_signature_scope")
    return errors


@pytest.fixture(scope="module")
def captured() -> dict:
    return _capture("versioned")


def test_installed_final_request_is_missing_required_version() -> None:
    request = _capture("original")
    assert request["params"]["Action"] == "SendEmail"
    assert "Version" not in request["params"]
    assert "action_or_version" in _violations(request)


def test_version_pinned_patch_passes_offline_contract(captured: dict) -> None:
    assert _violations(captured) == []
    assert captured["recipientCount"] == 1
    assert captured["params"]["Destination.ToAddresses.member.1"] == "controlled@example.test"
    assert captured["contentType"] is None  # query-only POST; AWS acceptance remains unverified
    assert "%40" in captured["rawQuery"] and "%3C" in captured["rawQuery"]


@pytest.mark.parametrize(("change", "expected"), [
    (lambda r: r["params"].update(**{"Destination.ToAddresses.member.1": ""}), "invalid_Destination.ToAddresses.member.1"),
    (lambda r: r["params"].update(**{"Destination.ToAddresses.member.2": "extra@example.test"}), "parameter_set_or_recipient_count"),
    (lambda r: r["params"].update(**{"Destination.ToAddresses.member.2": ""}), "parameter_set_or_recipient_count"),
    (lambda r: r["params"].pop("Source"), "invalid_Source"),
    (lambda r: r["params"].update(**{"Message.Subject.Data": ""}), "invalid_Message.Subject.Data"),
    (lambda r: r["params"].update(**{"Message.Body.Html.Data": ""}), "invalid_Message.Body.Html.Data"),
    (lambda r: r["params"].update(Source="invalid-address"), "invalid_Source"),
    (lambda r: r.update(host="email.us-east-1.amazonaws.com"), "endpoint_or_method"),
    (lambda r: r["params"].pop("Version"), "action_or_version"),
    (lambda r: r.update(rawQuery=r["rawQuery"] + "&raw=<html>"), "invalid_query_encoding"),
    (lambda r: r["params"].update(Unexpected="value"), "parameter_set_or_recipient_count"),
    (lambda r: r["params"].update(**{"Destination.ToAddresses.member.1": "csv@example.test"}), "recipient_isolation"),
])
def test_malformed_requests_rejected_by_offline_gate(captured: dict, change, expected: str) -> None:  # type: ignore[no-untyped-def]
    request = deepcopy(captured)
    change(request)
    assert expected in _violations(request)


def test_export_cannot_gain_additional_recipients() -> None:
    workflow = json.loads((ROOT / "workflows/notifications.json").read_text())
    ses = next(node for node in workflow["nodes"] if node["name"] == "AWS SES Send to Controlled Test Inbox")
    assert ses["parameters"]["toAddresses"] == ["={{ [$json.recipient] }}"]
    assert ses["parameters"]["additionalFields"] == {}
