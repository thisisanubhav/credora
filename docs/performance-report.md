# M9 performance report — local measurements only

Measured 2026-10-15 on macOS 26.5.2 arm64, Python 3.12.13, PostgreSQL 16.15 in OrbStack, n8n 2.43.5. The assignment's 10,000-row UTF-8 CSV was downloaded from its supplied Drive link (993,191 bytes). No live Gemini, SES, or AWS resource participated. Single observations are **not** p95 or capacity promises.

| Measurement | Actual result | Scope |
|---|---:|---|
| CSV parser + 10,000 inserts + transaction commit | 0.615 s; 16,270.5 rows/s | `uv run --frozen --env-file .env python -m benchmarks.ingestion.run`, dedicated `_qa_ingestion_test` DB |
| Instrumented row validation inside that run | 0.251 s | Sum of `validate_row` calls; overlaps total |
| Instrumented SQL INSERT execution | 0.295 s | Driver execute time; excludes some transaction/ORM overhead |
| Peak ingestion process RSS | 97,812,480 bytes (macOS `ru_maxrss`) | Process maximum, not per-batch allocation |
| 10,000 users × 50 synthetic products | 500,000 theoretical pairs | No naive LLM run |
| SQL candidate pairs / deterministic evaluations | 100,499 / 100,499 | 500 pages of 20 users, synthetic fixture |
| Matching SQL pages + evaluator | 8.058 s | Dedicated `_benchmark_test` DB; match writes/n8n **not** included |
| Whole matching benchmark command | 11.468 s | Includes sample fetch, test DB setup, seed, analyze, query plan |
| Peak matching process RSS | 117,489,664 bytes | macOS process maximum |
| First representative SQL page | 98 rows in 0.493 ms | `EXPLAIN (ANALYZE, BUFFERS)`; 20 selected users, warm single observation |
| Real three-user browser batch → Workflow C finish | 10.663 s | LocalStack + worker + dispatcher + actual n8n B/C + mock-only notification; batch `72a0cb08-0d1a-47e8-b846-73d9efcdbe76` |
| Actual matching execution / notification execution | 0.087 s / 0.147 s | PostgreSQL workflow timestamps for that batch; not total n8n scheduling latency |
| Outbox created → delivered | 4.589 s (ready), 5.026 s (completion) | Five-second dispatcher watch polling dominates this small run |
| Match inserts / notification groups / LLM calls | 3 / 2 / 0 | Clearly synthetic products, mock-only notification |

The matching plan used `users_pkey` index scans for the 20 selected user IDs, a 50-row `loan_products` sequential scan, then a join filter that removed 902 of 1,000 theoretical pairs on that page. PostgreSQL reported `Sort ... (actual time=0.437..0.439 rows=98)`, 74 shared-buffer hits and 0.493 ms execution time. The full raw plan was printed by `make matching-benchmark`; the page varies with UUID ordering, so do not compare this one page as a statistical distribution.

For the observed small end-to-end run, dispatcher polling/delivery waits dominate the 10.663 s elapsed time; matching and notification work are not the bottleneck. Reducing polling below five seconds would increase PostgreSQL/webhook checks and is not justified by a single local demo. At 10,000×50, candidate projection and deterministic evaluation are the main measured matching costs; 100,499 candidates remain a sizeable n8n workload. The benchmark does **not** persist 100,499 matches, execute Workflow B for 10,000 users, measure n8n page overhead at that scale, or send email. Those metrics remain **NOT_RUN**, not extrapolated.

Strategy A's 500,000 LLM requests are theoretical and were never made. Strategy B's local SQL+deterministic run is measured above. Strategy C's live Gemini latency/cost is **BLOCKED_BY_ZERO_BUDGET / unavailable credentials**; deterministic cases used zero LLM calls. The fixtures are not bank eligibility criteria. Re-run both benchmark commands on an otherwise idle machine for fresh numbers; keep the guarded test DBs separate from development and n8n databases.
