# Patched SES test preparation — blocked

Date: 2026-10-17

## Environment and safety

- Canonical worktree: populated SES worktree `enthusiastic-space-05804b95`.
- Branch: `feat/aws-ses-fresh-test-preparation`.
- Compose project: `loan-eligibility-engine`.
- Running n8n image verified: `sha256:3897004d6718a62a9d9e0d1e3656911690567e1f077e85fdc2dec6ce74caa04a`.
- n8n, PostgreSQL, LocalStack, and internal helper healthy. API and frontend available.
- Notification mode remains test, transport mock, SES enabled flag 0, maximum attempts 0.
- Scoped SES authorization remains unset. No dispatcher was started.

## Preparation result: BLOCKED

One new synthetic upload was submitted through FastAPI and its presigned LocalStack upload. The existing ingestion worker processed the exact uploaded object.

- Batch: `14b6b14b-5c56-4f6c-b54e-76cd5b5c73d2`.
- Batch status: `rejected`.
- Accepted rows: 0.
- Rejected rows: 1.
- Persisted row error: row 2, `invalid_email`.
- Cause: the preparation CSV used a reserved `.test` email domain rejected by the existing email validator. This was a preparation fixture error.
- New users: 0.
- Matching-request events for this batch: 0.
- Workflow B execution: NOT_RUN.
- Potential matches: 0; matching could not run without an accepted user.
- Matching-completed event: none.
- Pending or processing matching-completed events across the database: 0.
- Notification reservation: none; notification table fingerprint unchanged.
- SES authorization was not set.

The preparation script stopped after the worker result failed its processed-status assertion. Read-only database inspection confirmed the rejection. No upload, ingestion, event dispatch, or notification was retried. The rejected batch remains intact; no replacement batch was created.

## Preservation evidence

Before/after fingerprints matched for notification records, historical SES outbox events, recovery audit rows, loan products, published workflow configurations, and Workflow C execution records. All three historical SES notifications remain ambiguous with attempt count 1 and no SES Message ID. Their linked historical events remain delivered. Latest Workflow C execution remains 179.

## Verification limits and next step

Fresh offline SES contract and full regression suites: NOT_RUN after the mandatory preparation stop. Prior patch test results are not claimed as freshly executed here. No AWS or Gemini operation, Workflow C execution, or SES send occurred.

This preparation is not ready for a controlled SES attempt. A separately approved replacement preparation must first validate its synthetic CSV against the existing ingestion validator before creating a new batch. Preserve this rejected batch and all historical notification records. Future sending still requires separate explicit authorization.

## Authorized replacement preparation — PASS

The owner subsequently authorized resolving the rejected fixture. One replacement batch was created after its entire single-row CSV passed the existing `validate_row` validator locally. The previous rejected batch was preserved unchanged. No validator rules or loan products were modified.

| Evidence | Verified value |
| --- | --- |
| Replacement batch | `6fd3d3f1-6520-4c7d-9dab-141b152ac814` |
| Accepted / rejected rows | 1 / 0 |
| Matching-request event | `c4259083-7fcc-58cb-ba28-251e154ac74b` |
| Workflow B execution | `180`, terminal `success` |
| Potential matches | Exactly 1, explicitly synthetic product source |
| Matching-completed event | `747daee0-0fdc-554f-ab0b-07db40af6519` |
| Completion state | Pending, retry count 0; never dispatched |
| Pending/processing completion events globally | Exactly 1 |
| Notification reservations / SES attempts for new user | 0 / 0 |
| Published Workflow C version | `87b22acd-4324-40bd-94f2-6564255589a6` |
| Latest Workflow C execution | Unchanged at 179 |

The path used FastAPI, its presigned LocalStack upload, and the existing ingestion worker invoked for that exact object. Only the new matching-request event was dispatched, with the existing exact-event mechanism and authenticated Workflow B webhook. No background dispatcher was started.

The two existing scoped SES authorization fields in ignored local `.env` now match this replacement batch and its sole user's derived notification idempotency key. The key is not recorded here. No notification reservation was created. The helper was not restarted: future activation must reload scoped settings only after separate send authorization and a fresh safety preflight.

### Published configuration and runtime verification

- Running patched image remains `sha256:3897004d6718a62a9d9e0d1e3656911690567e1f077e85fdc2dec6ce74caa04a`.
- Published SES node contains exactly one recipient expression: `={{ [$json.recipient] }}`.
- Sender, subject, and HTML use their preflight fields; additional fields are empty and automatic node retry is disabled.
- Stored AWS credential remains attached; locally inspected credential metadata confirms region `eu-north-1` and keys present, without exporting their values.
- Published workflow fingerprint, including HMAC/preflight configuration, is unchanged.
- Sender and controlled recipient match; delivery does not derive from the CSV email.
- Running helper and `.env` remain test/mock, SES disabled, maximum attempts 0.
- PostgreSQL, LocalStack, n8n, and internal helper healthy; API, frontend, and n8n health endpoints respond successfully.

### Fresh regression evidence

- 129 tests passed across notification, recovery, matching, dispatcher, integration, unit, workflow parameter, HMAC, recipient isolation, and offline SES request-contract coverage.
- 2 new ingestion fixture regression cases passed: accepted example domain and rejected reserved test domain.
- Patched-image request capture runs with Docker networking disabled and synthetic credentials. Version `2010-12-01`, form-encoded body, sole recipient, and SigV4/body-tamper checks passed.
- Ruff passed; Mypy passed for 53 source files; Compose validation passed.
- Final database and history checks were repeated after regression: all three historical ambiguous notifications, their historical events, recovery audits, products, and Workflow C execution records remain unchanged.

IAM positive/negative simulation results remain owner-reported evidence, not independent AWS verification. No AWS/Gemini request or email send occurred. Offline tests do not prove AWS acceptance or inbox delivery.

### Future send prerequisites

Preparation is complete. A future send requires separate explicit authorization for the replacement batch and exact completion event above, a new safety/database preflight, one-attempt activation and helper reload, event-specific dispatch only, provider-result capture, owner inbox confirmation, and mandatory restoration to mock mode with scoped authorization cleared. Do not reuse historical notifications or the rejected batch. Do not run an unscoped dispatcher against this pending event.
