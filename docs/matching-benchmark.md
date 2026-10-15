# Matching benchmark

The benchmark command is `make matching-benchmark`. It downloads the assignment's 10,000-row sample at run time, discards its email values, stores only generated `@example.invalid` aliases in a dedicated `_benchmark_test` PostgreSQL database, and inserts 50 unmistakably synthetic fixture versions. It then runs the same keyset SQL prefilter and deterministic evaluator used by Workflow B. It prints raw counts, wall time, peak process RSS as reported by the OS, and `EXPLAIN (ANALYZE, BUFFERS)` for the first keyset page. The benchmark database is destructive **only within that guarded test database**; the application and n8n databases are not reset.

Strategy A (naive LLM-per-pair) is theoretical: 10,000 × 50 = 500,000 calls would be required, but no such paid calls are made and no latency/cost figure is invented. Strategy B is measured locally from SQL pages plus deterministic evaluation. Strategy C's live Gemini-dependent latency and cost are **BLOCKED** without an API key; deterministic calls remain zero for the supplied synthetic rules. This is not a claim of measured live C performance. The fixture distribution is based on the assignment sample and repeats a source-labelled synthetic profile rule to keep rule semantics constant, not to simulate 50 real bank products.

## Executed local result (2026-10-15)

One measured run after `ANALYZE`, on macOS 26.5.2 arm64, Python 3.12.13, PostgreSQL 16.15, and n8n 2.43.5 (n8n was not in the benchmark's hot path):

| Metric | Observed |
|---|---:|
| Actual assignment sample rows / CSV bytes | 10,000 / 993,191 |
| Synthetic product versions | 50 |
| Theoretical pairs | 500,000 |
| SQL candidate pairs / deterministic evaluations | 100,499 / 100,499 |
| Potential decisions, **not benchmark-persisted** | 100,499 |
| LLM calls | 0 |
| User-keyset pages | 500 |
| Matching phase (SQL pages + deterministic evaluation) | 7.734 s |
| Total command workload (sample download, guarded test-DB setup, seed, `ANALYZE`, matching, query plan) | 10.367 s |
| Peak benchmark-process RSS, macOS bytes | 113,754,112 (~108.5 MiB) |

`EXPLAIN (ANALYZE, BUFFERS)` for the first 20-user page returned 245 candidate pairs in 0.446 ms, with `users_pkey` index scans for the 20 selected user IDs and a 50-row product scan. This is a single warm-page observation, not a distribution or p95. The earlier unoptimized keyset-pair query took 68.853 s for the same candidate count; intermediate user pages took 22.693 s before materializing the selected user IDs. These were different query shapes, single runs on the same machine, **not** controlled repetitions. The final 7.734 s value is the one to reproduce.

| Strategy | Actually executed? | Calls / result | Interpretation |
|---|---|---|---|
| A — naive LLM per pair | **No** | 500,000 theoretical requests | Not a timing or cost measurement; intentionally avoided. |
| B — SQL + deterministic | **Yes** | 100,499 evaluated, zero LLM calls, 7.734 s matching phase | The measured local result above. Benchmark did not insert 100,499 match rows or run n8n, so this is not an end-to-end throughput claim. |
| C — SQL + selective Gemini | **No live Gemini call** | Zero calls for the deterministic fixture; model-dependent latency/cost blocked without a key | The optional advisory path is tested with mocks and bounded to five calls per run; no live C performance claimed. |

The fixture repeats one synthetic profile rule 49 times and has one synthetic INR income rule that the sample cannot satisfy because its income currency is unspecified. Thus the 100,499 potential decisions are *only* fixture outcomes, not bank-offer matches. Run the command again for fresh measurements; the sample download and host load can change. A full statistical benchmark would add warm-up and multiple repetitions, record raw times, and include actual n8n and match-write throughput before capacity planning.
