"""Offline SES request checks; never invoke a workflow or an AWS endpoint."""

from __future__ import annotations

import json
import os
import subprocess
import uuid
from pathlib import Path

import pytest
from botocore.session import get_session
from botocore.validate import ParamValidator

from scripts.db_admin import admin_connection
from services.notifications.content import DISCLAIMER, recipient_for, render

ROOT = Path(__file__).resolve().parents[2]
NODE_NAME = "AWS SES Send to Controlled Test Inbox"


def _ses_node() -> dict:
    workflow = json.loads((ROOT / "workflows/notifications.json").read_text())
    return next(node for node in workflow["nodes"] if node["name"] == NODE_NAME)


def _request(*, sender: str = "controlled@example.test", recipient: object = None,
             subject: object = "Synthetic demonstration matches",
             html: object = "<p>Potential match</p>") -> dict:
    if recipient is None:
        recipient = ["controlled@example.test"]
    return {"Source": sender, "Destination": {"ToAddresses": recipient},
            "Message": {"Subject": {"Data": subject},
                        "Body": {"Html": {"Data": html, "Charset": "UTF-8"}}}}


def _valid(params: dict) -> bool:
    shape = get_session().get_service_model("ses").operation_model("SendEmail").input_shape
    return not ParamValidator().validate(params, shape).has_errors()


def test_exported_ses_node_parameter_contract() -> None:
    node = _ses_node()
    params = node["parameters"]
    assert node["type"] == "n8n-nodes-base.awsSes"
    assert node["typeVersion"] == 1
    assert (params["resource"], params["operation"]) == ("email", "send")
    assert params["fromEmail"] == "={{ $json.sender }}"
    assert params["toAddresses"] == ["={{ [$json.recipient] }}"]
    assert params["subject"] == "={{ $json.subject }}"
    assert params["body"] == "={{ $json.html }}"
    assert params["isBodyHtml"] is True
    assert params["additionalFields"] == {}
    assert not node.get("retryOnFail")
    assert _valid(_request())


@pytest.mark.parametrize("change", [
    lambda p: p.pop("Source"),
    lambda p: p.update(Source=["controlled@example.test"]),
    lambda p: p["Destination"].update(ToAddresses="controlled@example.test"),
    lambda p: p["Destination"].update(ToAddresses=[["controlled@example.test"]]),
    lambda p: p["Message"].pop("Subject"),
    lambda p: p["Message"]["Subject"].pop("Data"),
    lambda p: p["Message"]["Subject"].update(Data=["wrong type"]),
    lambda p: p["Message"].pop("Body"),
    lambda p: p["Message"]["Body"]["Html"].pop("Data"),
    lambda p: p["Message"]["Body"]["Html"].update(Data=["wrong type"]),
])
def test_botocore_rejects_missing_or_wrong_type_fields(change) -> None:  # type: ignore[no-untyped-def]
    params = _request()
    change(params)
    assert not _valid(params)


@pytest.mark.parametrize("bad", ["", "missing-at.example.test", "bad address@example.test",
                                       "controlled@", " controlled@example.test "])
def test_controlled_recipient_rejects_malformed_configuration(monkeypatch, bad: str) -> None:
    monkeypatch.setenv("NOTIFICATION_MODE", "test")
    monkeypatch.setenv("NOTIFICATION_TRANSPORT", "ses")
    monkeypatch.setenv("NOTIFICATION_SES_ENABLED", "1")
    monkeypatch.setenv("NOTIFICATION_TEST_EMAIL", bad)
    if bad != " controlled@example.test ":
        with pytest.raises(ValueError, match="test_recipient_unconfigured"):
            recipient_for(uuid.uuid4())
    else:
        # Existing behavior trims configuration; the final SES address is clean.
        assert recipient_for(uuid.uuid4()) == "controlled@example.test"


def test_synthetic_message_and_csv_address_isolation(monkeypatch) -> None:
    monkeypatch.setenv("NOTIFICATION_MODE", "test")
    monkeypatch.setenv("NOTIFICATION_TRANSPORT", "ses")
    monkeypatch.setenv("NOTIFICATION_SES_ENABLED", "1")
    monkeypatch.setenv("NOTIFICATION_TEST_EMAIL", "controlled@example.test")
    controlled = recipient_for(uuid.uuid4())
    assert controlled != "csv-user@example.test"
    content = render([{"institution": "Synthetic Fixture", "name": "Profile Only",
                       "source_url": "https://example.test/product", "source_type": "synthetic",
                       "rate": None}], synthetic=True)
    assert content["subject"] and content["html"]
    assert DISCLAIMER in content["html"]
    assert _valid(_request(sender=controlled, recipient=[controlled],
                           subject=content["subject"], html=content["html"]))


def test_published_ses_parameters_match_export_when_n8n_is_available() -> None:
    if not os.environ.get("N8N_DB_NAME"):
        pytest.skip("n8n database not configured")
    try:
        with admin_connection(os.environ["N8N_DB_NAME"]) as conn, conn.cursor() as cursor:
            cursor.execute('SELECT active, "activeVersionId" FROM workflow_entity WHERE id = %s',
                           ("loanNotificationsM6",))
            row = cursor.fetchone()
            if row is None:
                pytest.skip("Workflow C is not imported")
            assert row[0] and row[1]
            cursor.execute('SELECT nodes FROM workflow_history WHERE "versionId" = %s', (row[1],))
            history = cursor.fetchone()
            assert history is not None
            nodes = history[0]
    except (KeyError, OSError) as error:
        pytest.skip(f"n8n database unavailable: {type(error).__name__}")
    published = next(node for node in nodes if node["name"] == NODE_NAME)
    exported = _ses_node()
    # n8n omits schema-default resource/operation values when the UI saves a node.
    normalized = {"resource": "email", "operation": "send", **published["parameters"]}
    assert normalized == exported["parameters"]
    assert published["typeVersion"] == exported["typeVersion"]
    assert bool(published.get("credentials"))


def test_installed_n8n_evaluates_recipient_as_single_string_array() -> None:
    compose = ["docker", "compose", "--project-directory", ".", "--env-file", ".env",
               "-f", "infrastructure/docker-compose.yml", "ps", "-q", "n8n"]
    try:
        container = subprocess.run(compose, cwd=ROOT, capture_output=True, text=True,
                                   check=True, timeout=5).stdout.strip()
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        pytest.skip("local n8n container unavailable")
    if not container:
        pytest.skip("local n8n container unavailable")
    script = """const fs=require('fs');
const root='/usr/local/lib/node_modules/n8n/node_modules/.pnpm/';
const pkg=fs.readdirSync(root).find(x=>x.startsWith('n8n-workflow@'));
const {Expression}=require(root+pkg+'/node_modules/n8n-workflow/dist/cjs/expression.js');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const value=new Expression('UTC').resolveSimpleParameterValue(input.expression,
  {$json:{recipient:'controlled@example.test'}},false);
console.log(JSON.stringify({array:Array.isArray(value),length:value.length,
  firstType:typeof value[0],nested:Array.isArray(value[0]),
  controlled:value[0]==='controlled@example.test'}));"""
    result = subprocess.run(["docker", "exec", "-i", container, "node", "-e", script],
                            input=json.dumps({"expression": _ses_node()["parameters"]["toAddresses"][0]}),
                            capture_output=True, text=True, check=True, timeout=10)
    assert json.loads(result.stdout) == {"array": True, "length": 1, "firstType": "string",
                                         "nested": False, "controlled": True}
