"""Idempotently add body-bound HMAC signing nodes to the three n8n exports.

Run only when rebuilding exports. The secret is referenced via n8n's environment,
never serialized into workflow JSON. This script does not contact any service.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
FILES = ("discovery.json", "matching.json", "notifications.json")


def _signer_code(body_expression: str, path: str) -> str:
    if body_expression:
        if not body_expression.startswith("={{ ") or not body_expression.endswith(" }}"):
            raise ValueError("unexpected n8n JSON body expression")
        body_js = body_expression[4:-3].replace("$json", "input")
        payload_js = f"JSON.parse({body_js})"
    else:
        payload_js = "{}"
    return (
        "const crypto = require('crypto');\n"
        "const canonical = value => Array.isArray(value) ? `[${value.map(canonical).join(',')}]` : "
        "(value !== null && typeof value === 'object' ? "
        "`{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonical(value[key])}`).join(',')}}` "
        ": JSON.stringify(value));\n"
        "return $input.all().map((item, index) => {\n"
        "  const input = item.json;\n"
        f"  const payload = {payload_js};\n"
        "  const key_id = $env.INTERNAL_STEP_KEY_ID;\n"
        "  const secret = $env.INTERNAL_STEP_SECRET;\n"
        "  if (!key_id || !secret || secret.length < 32) throw new Error('internal_signer_unconfigured');\n"
        "  const timestamp = String(Math.floor(Date.now() / 1000));\n"
        "  const nonce = crypto.randomUUID();\n"
        f"  const message = [key_id, timestamp, nonce, 'POST', '{path}', canonical(payload)].join('\\n');\n"
        "  const signature = crypto.createHmac('sha256', secret).update(message).digest('hex');\n"
        "  return {json: {payload, internal_auth: {key_id, timestamp, nonce, signature}}, pairedItem: {item: index}};\n"
        "});"
    )


def update(path: Path) -> int:
    workflow = json.loads(path.read_text(encoding="utf-8"))
    nodes = workflow["nodes"]
    connections = workflow["connections"]
    count = 0
    for node in list(nodes):
        if node["type"] != "n8n-nodes-base.httpRequest":
            continue
        parameters = node["parameters"]
        url = parameters.get("url", "")
        parsed = urlsplit(url)
        if parsed.hostname != "discovery" or parsed.port != 8001:
            continue
        signer_name = "Sign " + node["name"]
        if any(existing["name"] == signer_name for existing in nodes):
            continue
        expression = parameters.get("jsonBody", "")
        signer = {
            "id": "sign-" + node["id"], "name": signer_name,
            "type": "n8n-nodes-base.code", "typeVersion": 2,
            "position": [node["position"][0] - 110, node["position"][1] - 110],
            "parameters": {"jsCode": _signer_code(expression, parsed.path)},
        }
        nodes.append(signer)
        for source in connections.values():
            for branch in source.get("main", []):
                for edge in branch:
                    if edge["node"] == node["name"]:
                        edge["node"] = signer_name
        connections[signer_name] = {"main": [[{"node": node["name"], "type": "main", "index": 0}]]}
        parameters["sendBody"] = True
        parameters["specifyBody"] = "json"
        parameters["jsonBody"] = "={{ JSON.stringify($json.payload) }}"
        parameters["sendHeaders"] = True
        parameters["headerParameters"] = {"parameters": [
            {"name": "X-Internal-Key-Id", "value": "={{ $json.internal_auth.key_id }}"},
            {"name": "X-Internal-Timestamp", "value": "={{ $json.internal_auth.timestamp }}"},
            {"name": "X-Internal-Nonce", "value": "={{ $json.internal_auth.nonce }}"},
            {"name": "X-Internal-Signature", "value": "={{ $json.internal_auth.signature }}"},
        ]}
        count += 1
    path.write_text(json.dumps(workflow, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return count


if __name__ == "__main__":
    for filename in FILES:
        print(f"{filename}: {update(ROOT / 'workflows' / filename)} signing nodes added")
