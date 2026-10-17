# Diagnostic-image SES test preparation

Date: 2026-10-17. Status: local preparation complete; **no email sent**. A live attempt requires separate explicit authorization.

| Evidence | Verified value |
| --- | --- |
| Canonical branch | `feat/aws-ses-fresh-test-preparation` |
| n8n image | `sha256:7a6c3576b77f302b0ba1c13bb9de2ea2687487a52c5466a99dd6d248ff4586e2` |
| New batch | `6b524d02-204b-4b0a-b0e2-6ad260adf4d9` |
| Accepted / rejected rows | 1 / 0 |
| Matching-request event | `a032cb2a-956a-5cb6-995c-223dc00bad7f` |
| Workflow B | Execution `182`, terminal success |
| Potential matches | Exactly one, explicitly synthetic source; no official-bank match |
| Matching-completed event | `cbe2a3c8-d458-5781-8384-d6e8949d67e1` |
| Completion state | Pending, undispatched, retry count 0 |
| Global pending/processing completion events | Exactly one |
| Notification reservation / SES attempts for new user | None / zero |
| Workflow C version | `87b22acd-4324-40bd-94f2-6564255589a6` |
| Latest Workflow C execution | Unchanged at 181 |

The complete synthetic CSV row passed the existing ingestion validator before upload. Preparation used FastAPI's presigned LocalStack upload and the existing worker for the exact uploaded object. Only its matching-request event was dispatched through the authenticated Workflow B webhook. No notification dispatcher was started. No product or historical notification record was edited.

Published C has exactly one recipient expression `={{ [$json.recipient] }}`, preflight sender/subject/HTML fields, stored AWS credential in eu-north-1, unchanged HMAC/preflight configuration and no node retry. The diagnostic image is healthy. Sender and configured controlled recipient match and are independent of CSV email values.

The ignored local `.env` now holds this batch's scoped authorization and the recomputed unique notification idempotency key. The key is omitted here. No helper restart occurred: configuration and runtime remain test/mock, SES disabled, maximum attempts 0. The running helper still has no loaded send authorization. Future authorized activation must reload the helper with the correct diagnostic-image Compose override.

Before/after fingerprints confirm all four historical SES notifications, their delivered events, recovery audits, loan products, published workflows and Workflow C executions are unchanged. Historical notifications remain ambiguous with one attempt and no provider Message ID. The earlier rejected batch is unchanged.

No AWS or Gemini API was contacted. Owner-reported IAM simulations remain historical owner evidence, not independently reverified permissions. The diagnostic patch improves future failure evidence; it does not prove SES acceptance or receipt.

## Future handoff

Obtain explicit authorization for exactly one attempt for this batch and completion event. Repeat final safety/database checks; enable the scoped one-attempt configuration temporarily; reload only the helper using the canonical diagnostic-image override; dispatch only this event once. Inspect SES output and any safe status/code/request-ID diagnostics separately from workflow success. Restore mock/disabled/zero-attempt settings and clear scoped authorization regardless of outcome. Never replay an ambiguous notification. Confirm actual inbox receipt separately.

## Fresh verification

107 tests passed across notifications (including installed-image diagnostics/contract, HMAC, recipient isolation, recovery and idempotency), matching/dispatcher, and the synthetic CSV fixture. Ruff passed; Mypy passed for 54 source files; Compose validation with the current diagnostic-image override passed; `git diff --check` passed. Final post-test read-only checks reconfirmed all preservation assertions, the pending untouched event, no new reservation, correct scoped values, empty running-helper authorization and healthy local endpoints.


## Consumed by separately authorized attempt

This prepared event was dispatched once in Workflow C execution 183 on 2026-10-17 at 09:58 UTC. AWS returned HTTP 400 / MessageRejected; no SES Message ID exists. The resulting notification is ambiguous at one attempt. The event is delivered, authorization cleared and mock mode restored. **This batch/event is no longer available for a fresh attempt. Do not replay it.** See the latest live evidence.
