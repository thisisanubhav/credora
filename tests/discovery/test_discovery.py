"""Synthetic fixtures are separate from live-source and n8n execution evidence."""

from __future__ import annotations

import hashlib
import importlib
import json
import logging
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

from services.common.db import make_engine, session_scope
from services.common.internal_auth import sign, verify_and_reserve
from services.common.models import LoanProduct, WorkflowExecution
from services.discovery.crawler import CrawlError, fetch_source
from services.discovery.extraction import PageEvidence, extract_deterministic, validate_candidate
from services.discovery.gemini import GeminiError, structure_qualitative
from services.discovery.persistence import persist_product, record_source, start_run
from services.discovery.sources import SOURCES, require_source

crawler = importlib.import_module("services.discovery.crawler")
api = importlib.import_module("apps.discovery_api.main")
ROOT = Path(__file__).resolve().parents[2]


def fake_client(source_key: str, *, html: bytes | None = None, robots: bytes = b"User-agent: *\nAllow: /\n", status: int = 200):
    source = require_source(source_key)
    if html is None:
        html = (ROOT / "tests" / "fixtures" / "sources" / f"{source_key}_synthetic.html").read_bytes()

    def handler(request):
        assert str(request.url) in {source.origin + "/robots.txt", source.url}
        if str(request.url).endswith("robots.txt"):
            return httpx.Response(200, content=robots)
        return httpx.Response(status, content=html)

    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)


@pytest.fixture
def page(monkeypatch):
    monkeypatch.setattr(crawler, "_public_host", lambda _host: None)
    monkeypatch.setattr(crawler.time, "sleep", lambda _seconds: None)
    with fake_client("sbi") as client:
        return PageEvidence.model_validate(fetch_source("sbi", client=client))


@pytest.fixture(scope="module")
def db_engine():
    name = os.environ["TEST_DB_NAME"].removesuffix("_test") + "_discovery_test"
    assert name.endswith("_test") and name not in {os.environ["POSTGRES_DB"], os.environ["N8N_DB_NAME"]}
    old = os.environ.get("DATABASE_NAME")
    os.environ["DATABASE_NAME"] = name
    command.upgrade(Config("database/alembic.ini"), "head")
    engine = make_engine(role="migration", database=name)
    yield engine
    engine.dispose()
    if old is None:
        os.environ.pop("DATABASE_NAME", None)
    else:
        os.environ["DATABASE_NAME"] = old


@pytest.fixture
def clean_db(db_engine):
    with db_engine.begin() as connection:
        connection.execute(text("TRUNCATE TABLE loan_products, product_sources, workflow_executions CASCADE"))
    return db_engine


def test_allowlist_and_ssrf():
    assert len(SOURCES) == 2
    with pytest.raises(ValueError, match="source_not_allowlisted"):
        require_source("http://127.0.0.1/private")
    with pytest.raises(CrawlError, match="non_public_source_address"):
        crawler._public_host("localhost")


def test_html_extraction_rate_age_and_conditional_income(page):
    candidate = validate_candidate(extract_deterministic(page), page)
    assert candidate.interest_rate_min_pct == Decimal("11.25")
    assert candidate.min_age == 22
    assert candidate.currency_code == "INR"
    assert candidate.min_monthly_income is None  # Two conditional monthly tiers are not one rule.
    assert candidate.min_credit_score is None
    assert candidate.criterion_states["minimum_monthly_income"] == "UNKNOWN"
    assert candidate.criterion_states["minimum_age"] == "KNOWN"
    assert candidate.verification_status == "review_required"
    assert candidate.eligibility_rules.all[0].evidence.quote in page.eligibility_text


def test_axis_rate_period_and_maturity_age(monkeypatch):
    monkeypatch.setattr(crawler, "_public_host", lambda _host: None)
    monkeypatch.setattr(crawler.time, "sleep", lambda _seconds: None)
    with fake_client("axis") as client:
        page = PageEvidence.model_validate(fetch_source("axis", client=client))
    candidate = validate_candidate(extract_deterministic(page), page)
    assert candidate.interest_rate_min_pct == Decimal("12.50")
    assert candidate.criterion_states["interest_rate_period"] == "KNOWN"
    assert candidate.min_age == 22 and candidate.max_age is None


def test_annual_income_not_converted(page):
    changed = page.model_copy(update={"eligibility_text": page.eligibility_text.replace(
        "Minimum Net Monthly Salary", "Minimum annual income")})
    changed = changed.model_copy(update={"source_content_sha256": hashlib.sha256(
        (changed.eligibility_text + "\n" + changed.interest_rate_text).encode()).hexdigest()})
    candidate = extract_deterministic(changed)
    assert candidate.min_monthly_income is None
    assert candidate.criterion_states["minimum_monthly_income"] == "UNKNOWN"


def test_missing_eligibility_and_malformed_html(monkeypatch):
    monkeypatch.setattr(crawler, "_public_host", lambda _host: None)
    monkeypatch.setattr(crawler.time, "sleep", lambda _seconds: None)
    with fake_client("sbi", html=b"<html><body>Page layout changed</body></html>") as client, pytest.raises(CrawlError, match="eligibility_section_missing"):
        fetch_source("sbi", client=client)
    with fake_client("sbi", html=b"not html") as client, pytest.raises(CrawlError, match="non_html_response"):
        fetch_source("sbi", client=client)


def test_robots_redirect_and_oversize(monkeypatch):
    monkeypatch.setattr(crawler, "_public_host", lambda _host: None)
    monkeypatch.setattr(crawler.time, "sleep", lambda _seconds: None)
    with fake_client("sbi", robots=b"User-agent: *\nDisallow: /\n") as client, pytest.raises(CrawlError, match="robots_disallowed"):
        fetch_source("sbi", client=client)
    with fake_client("sbi", status=302) as client, pytest.raises(CrawlError, match="redirect_not_allowed"):
        fetch_source("sbi", client=client)
    with fake_client("sbi", html=b"<html>" + b"x" * (crawler.MAX_HTML_BYTES + 1)) as client, pytest.raises(CrawlError, match="response_too_large"):
        fetch_source("sbi", client=client)


def test_timeout_and_retry_exhaustion(monkeypatch):
    monkeypatch.setattr(crawler, "_public_host", lambda _host: None)
    monkeypatch.setattr(crawler.time, "sleep", lambda _seconds: None)

    def handler(_request):
        raise httpx.ReadTimeout("fixture timeout")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client, pytest.raises(CrawlError, match="retry_exhausted"):
        fetch_source("sbi", client=client)


def test_gemini_unavailable_and_malformed(page, monkeypatch):
    candidate = extract_deterministic(page)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    result, status = structure_qualitative(candidate, page)
    assert status == "unavailable" and result.extraction_method == "deterministic"
    monkeypatch.setenv("GEMINI_API_KEY", "test-only-key")
    with httpx.Client(transport=httpx.MockTransport(lambda _r: httpx.Response(200, json={"candidates": []}))) as client, pytest.raises(GeminiError, match="invalid_response"):
        structure_qualitative(candidate, page, client=client)


def test_gemini_schema_evidence_and_usage(page, monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="services.discovery.gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-only-key")
    candidate = extract_deterministic(page)
    quote = page.eligibility_text[:60]
    response = {"candidates": [{"content": {"parts": [{"text": json.dumps({"clauses": [
        {"text": quote, "evidence_quote": quote, "state": "UNKNOWN"},
    ]})}]}}], "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 8}}
    with httpx.Client(transport=httpx.MockTransport(lambda _r: httpx.Response(200, json=response))) as client:
        result, status = structure_qualitative(candidate, page, client=client)
    assert status == "used" and result.extraction_method == "mixed"
    assert result.model_name == "gemini-3.8-flash"
    assert "input=10 output=8" in caplog.text
    assert quote not in caplog.text
    response["candidates"][0]["content"]["parts"][0]["text"] = json.dumps({"clauses": [
        {"text": "invented", "evidence_quote": "invented", "state": "KNOWN"},
    ]})
    with httpx.Client(transport=httpx.MockTransport(lambda _r: httpx.Response(200, json=response))) as client, pytest.raises(GeminiError, match="unsupported_evidence"):
        structure_qualitative(extract_deterministic(page), page, client=client)


def test_validation_rejects_fabricated_rule(page):
    candidate = extract_deterministic(page)
    candidate.eligibility_rules.all[0].evidence.quote = "not on source page"
    with pytest.raises(ValueError, match="rule_evidence_not_in_source"):
        validate_candidate(candidate, page)


def test_product_versions_and_duplicate_detection(clean_db, page):
    candidate = validate_candidate(extract_deterministic(page), page)
    first, product_id, version = persist_product(clean_db, candidate)
    second, same_id, same_version = persist_product(clean_db, candidate)
    assert (first, second, product_id, version, same_id, same_version) == (
        "created", "unchanged", product_id, 1, product_id, 1,
    )
    changed_page = page.model_copy(update={"eligibility_text": page.eligibility_text.replace("22-58", "23-58")})
    changed_page = changed_page.model_copy(update={"source_content_sha256": hashlib.sha256(
        (changed_page.eligibility_text + "\n" + changed_page.interest_rate_text).encode()).hexdigest()})
    changed = validate_candidate(extract_deterministic(changed_page), changed_page)
    outcome, new_id, new_version = persist_product(clean_db, changed)
    assert (outcome, new_version) == ("versioned", 2)
    with session_scope(clean_db) as session:
        products = session.scalars(select(LoanProduct).order_by(LoanProduct.version)).all()
        assert len(products) == 2 and not products[0].is_current and products[1].is_current
        assert products[0].id == product_id and products[1].id == new_id


def test_incomplete_recrawl_preserves_verified_version(clean_db, page):
    # Persistence must protect a previously reviewed row if extraction regresses.
    synthetic = extract_deterministic(page)
    reviewed = synthetic.model_copy(update={
        "verification_status": "verified",
        "eligibility_rules": synthetic.eligibility_rules.model_copy(update={
            "completeness": "complete", "ambiguous": [], "unknown_reason": None,
        }),
    })
    outcome, first_id, version = persist_product(clean_db, reviewed)
    assert (outcome, version) == ("created", 1)
    changed_page = page.model_copy(update={"eligibility_text": page.eligibility_text + " Revised public copy."})
    changed_page = changed_page.model_copy(update={"source_content_sha256": hashlib.sha256(
        (changed_page.eligibility_text + "\n" + changed_page.interest_rate_text).encode(),
    ).hexdigest()})
    outcome, preserved_id, preserved_version = persist_product(clean_db, extract_deterministic(changed_page))
    assert (outcome, preserved_id, preserved_version) == ("preserved_verified", first_id, 1)
    with session_scope(clean_db) as session:
        assert session.scalar(select(func.count()).select_from(LoanProduct)) == 1


def test_concurrent_discovery_one_current(clean_db, page):
    candidate = extract_deterministic(page)
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _: persist_product(clean_db, candidate)[0], range(2)))
    assert sorted(outcomes) == ["created", "unchanged"]
    with session_scope(clean_db) as session:
        assert session.scalar(select(func.count()).select_from(LoanProduct)) == 1


def test_partial_failure_execution_tracking(clean_db, page):
    run_id = start_run(clean_db)
    persist_product(clean_db, extract_deterministic(page))
    record_source(clean_db, run_id, "sbi", "created")
    summary = record_source(clean_db, run_id, "axis", "failed")
    assert summary["run_status"] == "partial"
    with session_scope(clean_db) as session:
        assert session.get(WorkflowExecution, run_id).status == "partial"
        assert session.scalar(select(func.count()).select_from(LoanProduct)) == 1


def test_fixture_api_pipeline(clean_db, page, monkeypatch):
    monkeypatch.setattr(api, "_engine", lambda: clean_db)
    monkeypatch.setattr(api, "make_engine", lambda: clean_db)
    monkeypatch.setattr(api, "fetch_source", lambda _key: page.model_dump(mode="json"))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("INTERNAL_STEP_KEY_ID", "test-v1")
    monkeypatch.setenv("INTERNAL_STEP_SECRET", "t" * 64)
    with TestClient(api.app) as client:
        def signed_post(path, body):
            timestamp = str(int(time.time()))
            nonce = str(uuid.uuid4())
            return client.post(path, json=body, headers={
                "X-Internal-Key-Id": "test-v1", "X-Internal-Timestamp": timestamp,
                "X-Internal-Nonce": nonce,
                "X-Internal-Signature": sign(body, key_id="test-v1", timestamp=timestamp,
                                             nonce=nonce, method="POST", path=path, secret="t" * 64),
            })

        assert client.post("/discovery/runs", json={}).status_code == 401
        run = signed_post("/discovery/runs", {}).json()
        envelope = {"run_id": run["run_id"], "source_key": "sbi"}
        for step in ("fetch", "extract", "gemini", "validate", "persist", "record"):
            response = signed_post(f"/discovery/{step}", envelope)
            assert response.status_code == 200, step
            envelope = response.json()
        assert envelope["outcome"] == "created"
        assert envelope["llm_status"] == "unavailable"
        assert client.get("/health").status_code == 200
        assert signed_post("/discovery/fetch", {"source_key": "127.0.0.1"}).status_code == 422


def test_workflow_json_structure_and_no_secrets():
    raw = (ROOT / "workflows" / "discovery.json").read_text()
    workflow = json.loads(raw)
    names = {node["name"] for node in workflow["nodes"]}
    assert {"Daily Schedule", "Manual Trigger", "Source Configuration", "Fetch Official Source",
            "Extract Deterministic Criteria", "Needs Gemini?", "Gemini Qualitative Extraction",
            "Validate Source Evidence", "Persist Product Version", "Execution Summary"} <= names
    assert "GEMINI_API_KEY" not in raw and "APP_DB_PASSWORD" not in raw
    assert workflow["connections"]["Persist Product Version"]["main"][0][0]["node"] == "Sign Record Source Outcome"
    assert workflow["connections"]["Sign Record Source Outcome"]["main"][0][0]["node"] == "Record Source Outcome"


def test_internal_hmac_replay_expiry_route_and_rotation(clean_db, monkeypatch):
    monkeypatch.setenv("INTERNAL_STEP_KEY_ID", "new")
    monkeypatch.setenv("INTERNAL_STEP_SECRET", "n" * 64)
    monkeypatch.setenv("INTERNAL_STEP_PREVIOUS_KEY_ID", "old")
    monkeypatch.setenv("INTERNAL_STEP_PREVIOUS_SECRET", "o" * 64)
    body = {"run_id": "test", "nested": {"z": 2, "a": 1}}
    path = "/matching/batch"
    timestamp = str(int(time.time()))

    def headers(key_id, secret, *, ts=timestamp, nonce=None):
        nonce = nonce or str(uuid.uuid4())
        return {"X-Internal-Key-Id": key_id, "X-Internal-Timestamp": ts,
                "X-Internal-Nonce": nonce, "X-Internal-Signature": sign(
                    body, key_id=key_id, timestamp=ts, nonce=nonce,
                    method="POST", path=path, secret=secret)}

    current = headers("new", "n" * 64)
    assert verify_and_reserve(clean_db, body, current, method="POST", path=path)
    assert not verify_and_reserve(clean_db, body, current, method="POST", path=path)
    assert not verify_and_reserve(clean_db, body, headers("new", "wrong" * 12), method="POST", path=path)
    assert not verify_and_reserve(clean_db, body, headers("new", "n" * 64), method="POST", path="/matching/complete")
    assert not verify_and_reserve(clean_db, body, headers("new", "n" * 64,
                                                           ts=str(int(time.time()) - 301)), method="POST", path=path)
    assert verify_and_reserve(clean_db, body, headers("old", "o" * 64), method="POST", path=path)


def test_all_internal_n8n_steps_are_signed_and_webhooks_save_terminal_runs():
    for filename in ("discovery.json", "matching.json", "notifications.json"):
        raw = (ROOT / "workflows" / filename).read_text(encoding="utf-8")
        workflow = json.loads(raw)
        nodes = {node["name"]: node for node in workflow["nodes"]}
        for node in workflow["nodes"]:
            if node["type"] != "n8n-nodes-base.httpRequest":
                continue
            if not node["parameters"].get("url", "").startswith("http://discovery:8001/"):
                continue
            assert "Sign " + node["name"] in nodes
            assert node["parameters"]["jsonBody"] == "={{ JSON.stringify($json.payload) }}"
            names = {item["name"] for item in node["parameters"]["headerParameters"]["parameters"]}
            assert names == {"X-Internal-Key-Id", "X-Internal-Timestamp",
                             "X-Internal-Nonce", "X-Internal-Signature"}
        assert "INTERNAL_STEP_SECRET=" not in raw
        if filename != "discovery.json":
            assert workflow["settings"]["saveDataSuccessExecution"] == "all"
            assert workflow["settings"]["saveDataErrorExecution"] == "all"


def test_concurrent_internal_nonce_claim_has_one_winner(clean_db, monkeypatch):
    monkeypatch.setenv("INTERNAL_STEP_KEY_ID", "concurrent")
    monkeypatch.setenv("INTERNAL_STEP_SECRET", "c" * 64)
    body = {"run_id": "concurrent-fixture"}
    timestamp = str(int(time.time()))
    nonce = str(uuid.uuid4())
    headers = {"X-Internal-Key-Id": "concurrent", "X-Internal-Timestamp": timestamp,
               "X-Internal-Nonce": nonce,
               "X-Internal-Signature": sign(body, key_id="concurrent", timestamp=timestamp,
                                            nonce=nonce, method="POST", path="/matching/batch",
                                            secret="c" * 64)}
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: verify_and_reserve(
            clean_db, body, headers, method="POST", path="/matching/batch"), range(2)))
    assert sorted(outcomes) == [False, True]
