# Fresh synthetic SES demonstration batch — prepared, not sent

Prepared on 2026-10-17 in the canonical `loan-eligibility-engine` Compose environment on local branch `feat/aws-ses-fresh-test-preparation`. **No AWS or Gemini API call, Workflow C execution, notification dispatch, or email send occurred during this preparation.** The owner reports an IAM Policy Simulator result of **ALLOWED** for the verified sender and authorized recipient and **DENIED** for an unauthorized recipient. Those console results were not independently reproduced during this task; see [the prior IAM verification record](aws-ses-iam-verification.md).

| Boundary | Sanitized result | Status |
|---|---|---|
| Browser → FastAPI → LocalStack → ingestion worker | One new synthetic CSV row uploaded through the visible demo checkbox; API presign returned 201; browser reached “Ingestion complete” | PASS |
| Upload batch | `adcf1f84-f6b6-4dad-9010-c613c037553f`; `is_demo=true`; final status `matched`; one accepted user, zero rejected | PASS |
| New user | Internal UUID `25222cb1-8106-4cf8-aa14-fbfd1a557136`; unique synthetic source ID; valid local fixture values; no real personal information | PASS |
| Matching-request event | `1496ebb1-cd72-5c70-952c-7607c6ab6d2a`; `upload_batch.ready.v1`; targeted dispatch returned `delivered` with one claim | PASS |
| Workflow B | Published n8n execution **178**, terminal `success`; application matching run succeeded; zero LLM calls | PASS |
| Potential match | Exactly one, `e18e4919-1153-4f16-ba05-c0d7b92e0544`, deterministic, to the current verified **SYNTHETIC DEMO — profile-only** product; zero official-bank matches | PASS |
| Completion event | `ec5a0972-60b1-5107-b136-45437c7e55e5`; `matching.completed.v1`; the only pending/processing outbox event; retry count zero; **not dispatched** | PASS |
| Intended notification | One logical notification is identified by the sole batch/user match and the existing `potential-v1` idempotency formula. No notification row has been reserved or attempted. | PREPARED |
| Scoped authorization | Ignored `.env` contains this batch UUID and the exact recomputed 64-character idempotency key under `NOTIFICATION_SES_AUTHORIZED_BATCH_ID` and `NOTIFICATION_SES_AUTHORIZED_IDEMPOTENCY_KEY`. The key is unique and omitted here; `.env` remains mode 0600 and ignored by Git. | PASS |
| Historical isolation | Both older SES notifications remain `ambiguous`, each at one attempt with no Message ID. Their outbox events were not replayed; recovery audits were not changed. | PASS |
| Workflow C | Latest execution remains **177**; no new reservation or execution | PASS |
| Current runtime | `NOTIFICATION_MODE=test`, `NOTIFICATION_TRANSPORT=mock`, `NOTIFICATION_SES_ENABLED=0`, `NOTIFICATION_SES_MAX_ATTEMPTS=0`; helper healthy; notification dispatcher stopped | PASS |
| Published SES node | Active Workflow C version `ca115f84-8244-4d83-9739-d830a00f09da` binds a stored AWS credential in `eu-north-1`; `email/send` uses `={{ $json.sender }}` and `={{ [$json.recipient] }}`; no additional recipient or retry is configured | PASS |

The configured sender and controlled recipient are equal, non-placeholder local values. The application derives the SES recipient from `NOTIFICATION_TEST_EMAIL`, never from the CSV row. The actual address is intentionally omitted. The synthetic product is an explicitly labelled demonstration fixture, not an SBI or Axis offering. No official-bank product row was changed.

The frontend's existing `NEXT_PUBLIC_ENABLE_DEMO_UPLOAD=1` flag was enabled only for the browser upload. Its normal development process was then restarted without that flag; the checkbox is hidden again, while frontend and API both return HTTP 200. Fresh isolated regression checks passed: 44 notification/recovery tests, 17 matching tests, 27 database/unit tests, Ruff, mypy, Compose configuration validation, and all three workflow JSON parses. One matching concurrency test initially exposed a clock-sensitive fixture; its test-only due time was made explicit and the full matching suite passed on rerun. No regression test used the canonical application database for destructive setup.

## Future one-send handoff — **do not execute as part of preparation**

1. Obtain separate authorization for one real SES attempt. Have an authorized AWS console operator recheck the actual attached policy and default version, exact verified identity ARN, and the owner-reported positive **ALLOWED** / negative **DENIED** simulation context. Confirm the same verified identity remains permitted in the SES sandbox in `eu-north-1`. A simulator result does not prove provider acceptance or inbox delivery.
2. Immediately before sending, recheck this exact batch and user: one synthetic potential match, no notification row or prior attempt, and only completion event `ec5a0972-60b1-5107-b136-45437c7e55e5` pending. Confirm no dispatcher is running, no unrelated event is due, Workflow C's published credential and sender/recipient expressions are unchanged, and both old ambiguous notifications remain untouched. Stop if any condition differs.
3. In ignored local `.env` only, retain the batch-scoped authorization values and controlled sender/recipient. Temporarily set `NOTIFICATION_TRANSPORT=ses`, `NOTIFICATION_SES_ENABLED=1`, and `NOTIFICATION_SES_MAX_ATTEMPTS=1`, keeping `NOTIFICATION_MODE=test`. Validate configuration, refresh only the internal `discovery` helper with the documented Compose command, and verify effective settings without printing identities or credentials. Do not run an unscoped dispatcher.
4. Dispatch **only** event `ec5a0972-60b1-5107-b136-45437c7e55e5` through `dispatch_once(engine, only_event_id=...)`. This is the sole intended Workflow C invocation. Do not retry automatically after a timeout or ambiguous provider result.
5. Inspect the SES node output separately from n8n's terminal workflow status. Record the provider response and Message ID only if SES actually accepts the request. Independently verify the controlled Gmail Inbox/Spam receipt and capture sanitized evidence; a Message ID alone is not receipt evidence.
6. Regardless of outcome, stop any dispatch activity, restore `NOTIFICATION_TRANSPORT=mock`, `NOTIFICATION_SES_ENABLED=0`, and `NOTIFICATION_SES_MAX_ATTEMPTS=0`; clear both `NOTIFICATION_SES_AUTHORIZED_*` values; refresh the helper and verify its effective mock/disabled state. Preserve a `sending` or `ambiguous` reservation if provider acceptance is uncertain. Never reset attempts or replay this event to force another send.

This batch is prepared for a **separately authorized** one-send test. It is not evidence of an SES send or received email.
