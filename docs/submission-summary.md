# Loan Eligibility Engine — private reviewer summary

## Latest SES outcome — PASS, execution 185 (2026-10-17 10:26 UTC)

One separately authorized attempt was accepted by AWS SES in `eu-north-1`. The controlled Gmail recipient confirmed receipt with the synthetic product label and required disclaimer. Notification state is `sent`, attempt count **1**, with a persisted provider Message ID. Mock transport is restored, SES disabled, maximum attempts zero, scoped authorization cleared, and dispatcher stopped. Five historical ambiguous notifications are unchanged. See [successful delivery evidence](aws-ses-success-evidence.md).

This supersedes historical failed-attempt summaries below. Live SES sending and owner-confirmed receipt are **PASS**; a received-email screenshot/video has not yet been supplied. Live Gemini use, evaluator access, demonstration video, and submission remain incomplete. The project is not fully submission-ready.

## Latest SES result — execution 183, 2026-10-17 09:58 UTC

**FAIL for provider acceptance.** One separately authorized attempt on the diagnostic image returned HTTP **400**, AWS **MessageRejected**, request ID `27ff80c4-8694-49f5-bdab-7356ef54d0cb`, with no SES Message ID. Workflow success reflects a handled error. The notification is ambiguous at one attempt; four previous ambiguous records are unchanged. Mock mode is restored, SES disabled, scoped authorization cleared, dispatcher stopped, and no completion event is pending. The owner checked the controlled inbox and confirmed no email received. This supersedes earlier attempt summaries below. Actual SES delivery remains incomplete; no submission readiness is claimed. See [live evidence](aws-ses-live-evidence.md#diagnostic-image-single-attempt--execution-183).

## Latest controlled attempt — 2026-10-17 09:34 UTC

**FAIL for SES acceptance and receipt: the owner confirmed no email received.** The single authorized attempt on the patched n8n image reached Workflow C execution **181**. The SES node ran once and returned `Bad request - please check your parameters`, without a Message ID. Terminal workflow success reflects handled failure. Notification `514f933f-277e-43e3-88e1-2284519bd1dc` remains ambiguous, attempt count 1. There are now four ambiguous SES notifications; the previous three are unchanged. Mock mode is restored, SES disabled, maximum attempts 0, scoped authorization cleared, and no completion event remains pending. No retry is authorized. See [live evidence](aws-ses-live-evidence.md#patched-image-controlled-attempt--execution-181). Actual SES delivery remains incomplete; no submission readiness is claimed.

Repository: <https://github.com/thisisanubhav/loan-eligibility-engine> (private). Verified published M10 baseline commit: `b189c16d7fc90b7dc98a3e6f6c3de47086732db5`; M9.1 ancestor: `fe09a9c`. The final M10 tip must be taken from the pushed branch (`git rev-parse HEAD` and `git ls-remote origin refs/heads/feat/m10-submission-readiness`) rather than hard-coded into its own commit. Video: **not recorded or linked**. Submission form: <https://docs.google.com/forms/d/e/1FAIpQLSe1ET4U8rOcPM3VGJ8fT5HhigTO9fKuDlsB_wHtB5acWys9XQ/viewform> (not submitted).

## Current local release state — 2026-10-17

The canonical development copy is the populated SES worktree on `feat/aws-ses-final-test-preparation`, with Compose project `loan-eligibility-engine`. Its application and n8n state were backed up locally, then checked after moving host API/frontend/ingestion processes to that worktree. The older restart worktree has a separate empty application database. See [environment reconciliation](environment-reconciliation.md) for ownership, ports, and preserved record IDs, and [fresh release verification](release-verification.md) for the isolated regression and security checks. The SES source branch is a descendant of the current remote default; publication is verified only by checking the remote branch after push.

The latest separately authorized SES attempt used a fresh synthetic batch and reached Workflow C execution **179**. Its SES node returned `Bad request - please check your parameters`; no provider Message ID or accepted-send response was retained. The new notification is `ambiguous` after one attempt, alongside two earlier ambiguous records. The owner checked Inbox and Spam and confirmed no email was received. Mock transport is restored and the dispatcher is stopped. Live Gemini use, evaluator access, the demonstration video, and the submission form remain incomplete. This repository is **not assignment submission-ready**.

## Architecture and stack

Next.js 16/TypeScript/Tailwind provides a minimal CSV upload page. FastAPI issues short-lived presigned S3 POSTs; a Python 3.12 ingestion handler streams CSV into PostgreSQL and commits a transactional outbox event. A signed dispatcher invokes self-hosted n8n Workflow B for SQL-first, deterministic, fail-closed matching; its completion event triggers Workflow C for grouped, test-only notifications. Separately, scheduled Workflow A crawls allowlisted official SBI and Axis pages, preserves source evidence, and versions partial criteria. Docker Compose runs PostgreSQL 16, n8n 2.43.5, LocalStack S3 and the private helper. `infrastructure/serverless.yml` and a local Lambda zip demonstrate future AWS shape but have **not** been deployed. [Architecture diagrams](final-architecture.md), [README quick start](../README.md) and [workflow exports](../workflows/) are the reviewer entry points.

## Measured evidence, not extrapolation

The supplied 10,000-row sample was parsed/persisted in a guarded local test database in 0.615 s (one run; 97,812,480-byte peak process RSS). A 10,000-user × 50-**synthetic**-product benchmark considered 500,000 theoretical pairs, projected 100,499 SQL candidates (79.9% fewer), took 8.058 s for SQL paging plus deterministic evaluation, and made zero LLM calls (117,489,664-byte process RSS). It did **not** persist matches or run n8n at that scale. Reproduce with `uv run --frozen --env-file .env python -m benchmarks.ingestion.run` and `make matching-benchmark`; see [scope and EXPLAIN notes](performance-report.md).

The isolated clean clone produced one real browser/LocalStack batch with 3 accepted synthetic users, 3 versioned potential matches, 2 mock-only notification records and terminal n8n B/C executions 34/35. Discovery execution 36 fetched SBI and Axis, both `review_required`; recrawl left one version each. See [clean-checkout evidence](submission-checklist.md), [screenshots](../artifacts/m10/real-ingestion-complete.png), and [prior QA evidence](final-test-evidence.md).

After that baseline, one separately authorized, batch-scoped real SES test reached published n8n Workflow C execution **177** and its SES node exactly once. The node returned `Forbidden - perhaps check your credentials?`; no SES Message ID was returned, the notification is conservatively `ambiguous` with one attempt, and the owner reported **no inbox receipt**. Mock mode and zero-attempt settings were restored. This is **not** a successful SES demonstration; see [sanitized live evidence](aws-ses-live-evidence.md). No retry is authorized.

On 2026-10-17, the owner authorized one attempt on fresh batch `adcf1f84-f6b6-4dad-9010-c613c037553f`. Exact-event dispatch reached Workflow C **179** once; the SES node returned `Bad request - please check your parameters`. There was no Message ID or accepted-send evidence. The new notification remains `ambiguous`, attempt count one, with no retry. Test/mock/disabled/zero settings and cleared scoped authorization were verified after rollback. The owner confirmed no Inbox or Spam receipt; [the latest evidence](aws-ses-live-evidence.md) records the exact boundary.

## Honest limitations

- The budget is ₹0: no RDS, real S3/Lambda, verified AWS SES delivery, inbox receipt or live Gemini request. The authorized SES attempts have produced no Message ID; LocalStack/fixtures/mocks must not be represented as live AWS services.
- Official bank eligibility remains incomplete, and sample income has no currency. Neither bank is automatically matched; synthetic fixtures are clearly separate.
- The future AWS JWT API lacks a browser OIDC login, RDS certificate verification and privately hosted n8n. The local editor's Code signer is unsuitable for multi-user hosting.
- The installed n8n SES node cannot send both HTML and plain-text alternatives in one `email.send` call. An actual received SES email—required by the PDF—has not been demonstrated.
- The required 5–10 minute video does not yet exist. The owner must record it, verify access, and submit the form. The time limit cannot be checked without the assignment email receipt timestamp.

The PDF specifies four evaluator accounts, but the owner later explicitly directed that no evaluator be invited. The four previously pending invitations were canceled before acceptance. GitHub now lists no pending invitations and only the owner as collaborator. This leaves the PDF's evaluator-access requirement unmet; the private repository is not accessible to those accounts.
