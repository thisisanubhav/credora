# Loan Eligibility Engine — private reviewer summary

Repository: <https://github.com/thisisanubhav/loan-eligibility-engine> (private). Verified published M10 baseline commit: `b189c16d7fc90b7dc98a3e6f6c3de47086732db5`; M9.1 ancestor: `fe09a9c`. The final M10 tip must be taken from the pushed branch (`git rev-parse HEAD` and `git ls-remote origin refs/heads/feat/m10-submission-readiness`) rather than hard-coded into its own commit. Video: **not recorded or linked**. Submission form: <https://docs.google.com/forms/d/e/1FAIpQLSe1ET4U8rOcPM3VGJ8fT5HhigTO9fKuDlsB_wHtB5acWys9XQ/viewform> (not submitted).

## Architecture and stack

Next.js 16/TypeScript/Tailwind provides a minimal CSV upload page. FastAPI issues short-lived presigned S3 POSTs; a Python 3.12 ingestion handler streams CSV into PostgreSQL and commits a transactional outbox event. A signed dispatcher invokes self-hosted n8n Workflow B for SQL-first, deterministic, fail-closed matching; its completion event triggers Workflow C for grouped, test-only notifications. Separately, scheduled Workflow A crawls allowlisted official SBI and Axis pages, preserves source evidence, and versions partial criteria. Docker Compose runs PostgreSQL 16, n8n 2.43.5, LocalStack S3 and the private helper. `infrastructure/serverless.yml` and a local Lambda zip demonstrate future AWS shape but have **not** been deployed. [Architecture diagrams](final-architecture.md), [README quick start](../README.md) and [workflow exports](../workflows/) are the reviewer entry points.

## Measured evidence, not extrapolation

The supplied 10,000-row sample was parsed/persisted in a guarded local test database in 0.615 s (one run; 97,812,480-byte peak process RSS). A 10,000-user × 50-**synthetic**-product benchmark considered 500,000 theoretical pairs, projected 100,499 SQL candidates (79.9% fewer), took 8.058 s for SQL paging plus deterministic evaluation, and made zero LLM calls (117,489,664-byte process RSS). It did **not** persist matches or run n8n at that scale. Reproduce with `uv run --frozen --env-file .env python -m benchmarks.ingestion.run` and `make matching-benchmark`; see [scope and EXPLAIN notes](performance-report.md).

The isolated clean clone produced one real browser/LocalStack batch with 3 accepted synthetic users, 3 versioned potential matches, 2 mock-only notification records and terminal n8n B/C executions 34/35. Discovery execution 36 fetched SBI and Axis, both `review_required`; recrawl left one version each. See [clean-checkout evidence](submission-checklist.md), [screenshots](../artifacts/m10/real-ingestion-complete.png), and [prior QA evidence](final-test-evidence.md).

After that baseline, one separately authorized, batch-scoped real SES test reached published n8n Workflow C execution **177** and its SES node exactly once. The node returned `Forbidden - perhaps check your credentials?`; no SES Message ID was returned, the notification is conservatively `ambiguous` with one attempt, and the owner reported **no inbox receipt**. Mock mode and zero-attempt settings were restored. This is **not** a successful SES demonstration; see [sanitized live evidence](aws-ses-live-evidence.md). No retry is authorized.

## Honest limitations

- The budget is ₹0: no RDS, real S3/Lambda, AWS SES delivery, inbox receipt or live Gemini request. The one SES attempt was owner-authorized under owner-confirmed spending safeguards but failed; LocalStack/fixtures/mocks must not be represented as live AWS services.
- Official bank eligibility remains incomplete, and sample income has no currency. Neither bank is automatically matched; synthetic fixtures are clearly separate.
- The future AWS JWT API lacks a browser OIDC login, RDS certificate verification and privately hosted n8n. The local editor's Code signer is unsuitable for multi-user hosting.
- The installed n8n SES node cannot send both HTML and plain-text alternatives in one `email.send` call. An actual received SES email—required by the PDF—has not been demonstrated.
- The required 5–10 minute video does not yet exist. The owner must record it, verify access, and submit the form. The time limit cannot be checked without the assignment email receipt timestamp.

The PDF specifies four evaluator accounts, but the owner later explicitly directed that no evaluator be invited. The four previously pending invitations were canceled before acceptance. GitHub now lists no pending invitations and only the owner as collaborator. This leaves the PDF's evaluator-access requirement unmet; the private repository is not accessible to those accounts.
