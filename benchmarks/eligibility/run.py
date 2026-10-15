"""Reproducible 10k×50 local benchmark; never stores the sample's real email values."""

from __future__ import annotations

import csv
import io
import os
import platform
import resource
import time
import uuid
from decimal import Decimal

import httpx
from alembic import command
from alembic.config import Config
from sqlalchemy import func, insert, select, text

from scripts.db_admin import test_database
from scripts.seed_matching_demo import SOURCE_ID, seed_synthetic
from services.common.db import make_engine, session_scope
from services.common.models import LoanProduct, UploadBatch, User, WorkflowExecution
from services.eligibility.rules import ProductFacts, UserFacts, evaluate
from services.eligibility.storage import PREFILTER_SQL, candidate_page

SAMPLE_URL = "https://drive.google.com/uc?export=download&id=1KBaZRkfr7T2kVBKSr_2fr7v2tTe6f8qu"


def main() -> None:
    total_begin = time.perf_counter()
    test_database(benchmark=True)
    name = os.environ["TEST_DB_NAME"].removesuffix("_test") + "_benchmark_test"
    os.environ["DATABASE_NAME"] = name
    command.upgrade(Config("database/alembic.ini"), "head")
    engine = make_engine(role="migration", database=name)
    try:
        with httpx.Client(follow_redirects=True, timeout=30) as client:
            response = client.get(SAMPLE_URL)
            response.raise_for_status()
            if len(response.content) > 1_500_000:
                raise RuntimeError("sample too large for benchmark contract")
            rows = list(csv.DictReader(io.StringIO(response.text)))
        if len(rows) != 10_000:
            raise RuntimeError(f"expected 10000 sample records; received {len(rows)}")
        with engine.begin() as connection:
            connection.execute(text("TRUNCATE TABLE notification_matches, notification_logs, matches, workflow_executions, outbox_events, upload_row_errors, users, upload_batches, loan_products, product_sources CASCADE"))
        seed_synthetic(engine)
        batch_id = uuid.uuid4()
        with session_scope(engine) as session:
            session.add(UploadBatch(id=batch_id, object_bucket="benchmark", object_key=f"benchmark/{batch_id}.csv",
                schema_version=1, status="processed", accepted_rows=10_000, total_rows=10_000, is_demo=True))
            session.flush()
            template = session.scalar(select(LoanProduct).where(LoanProduct.source_id == SOURCE_ID,
                LoanProduct.source_product_key == "demo-profile"))
            if template is None:
                raise RuntimeError("synthetic benchmark template missing")
            for number in range(48):
                session.add(LoanProduct(id=uuid.uuid5(uuid.NAMESPACE_URL, f"benchmark-product-{number}"),
                    source_id=SOURCE_ID, source_product_key=f"benchmark-{number}", version=1,
                    is_current=True, product_name=f"SYNTHETIC BENCHMARK {number}", source_url=template.source_url,
                    currency_code=None, criterion_states=template.criterion_states,
                    eligibility_rules=template.eligibility_rules, rule_schema_version=1,
                    raw_eligibility_text=template.raw_eligibility_text,
                    source_content_sha256=template.source_content_sha256, extraction_method="deterministic",
                    verification_status="verified", retrieved_at=template.retrieved_at,
                    last_seen_at=template.last_seen_at, min_age=template.min_age,
                    min_credit_score=template.min_credit_score,
                    eligible_employment_statuses=template.eligible_employment_statuses))
            session.flush()
            for offset in range(0, len(rows), 500):
                values = []
                for number, row in enumerate(rows[offset:offset + 500], offset):
                    raw = row["employment_status"]
                    normalized = {"salaried": "salaried", "self-employed": "self_employed"}.get(raw.casefold(), "other")
                    values.append({"id": uuid.uuid5(uuid.NAMESPACE_URL, f"{batch_id}:{number}"),
                        "upload_batch_id": batch_id, "source_user_id": row["user_id"],
                        "email": f"benchmark-{number}@example.invalid",
                        "monthly_income": Decimal(row["monthly_income"]), "income_currency": None,
                        "credit_score": int(row["credit_score"]), "age": int(row["age"]),
                        "employment_status": normalized, "employment_status_raw": raw})
                session.execute(insert(User), values)
            run = WorkflowExecution(workflow_type="matching", upload_batch_id=batch_id,
                status="running", metrics={"pages": {}})
            session.add(run)
            session.flush()
            run_id = run.id
        with engine.begin() as connection:
            connection.execute(text("ANALYZE users, loan_products, product_sources"))
        cursor = None
        candidates = eligible = pages = 0
        begin = time.perf_counter()
        while True:
            page = candidate_page(engine, run_id, cursor)
            pages += 1
            for pair in page["candidates"]:
                item = dict(pair["user"])
                item["monthly_income"] = Decimal(item["monthly_income"])
                decision = evaluate(UserFacts.model_validate(item), ProductFacts.model_validate(pair["product"]),
                                    demo_batch=True)
                candidates += 1
                eligible += decision.status == "ELIGIBLE_POTENTIAL"
            cursor = page["next_cursor"]
            if cursor is None:
                break
        elapsed = time.perf_counter() - begin
        with session_scope(engine) as session:
            product_count = session.scalar(select(func.count()).select_from(LoanProduct))
            assert product_count is not None
            first_users = session.scalars(select(User.id).where(User.upload_batch_id == batch_id).order_by(User.id).limit(20)).all()
            plan = session.execute(text("EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) " + PREFILTER_SQL), {
                "batch_id": batch_id, "demo_batch": True, "user_ids": first_users,
            }).scalars().all()
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        print({"sample_rows": len(rows), "sample_bytes": len(response.content),
               "products": product_count, "theoretical_pairs": len(rows) * product_count,
               "sql_candidates": candidates, "deterministic_evaluations": candidates,
               "potential_pairs": eligible, "llm_calls": 0, "pages": pages,
               "matching_seconds": round(elapsed, 3),
               "total_seconds": round(time.perf_counter() - total_begin, 3),
               "peak_rss_raw": peak,
               "platform": platform.platform(), "python": platform.python_version()})
        print("EXPLAIN ANALYZE (first keyset page):")
        for line in plan:
            print(line)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
