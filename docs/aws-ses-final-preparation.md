# Isolated SES demonstration batch — prepared, not sent

Local evidence captured on 2026-10-16. **No Workflow C execution or AWS request occurred.** The controlled sender and recipient were checked for equality and non-placeholder values without recording either address. The n8n AWS credential's configured region is `eu-north-1`; the IAM username/access-key association was manually confirmed by the owner, not independently queried from AWS in this task.

| Boundary | Sanitized evidence | Status |
|---|---|---|
| Browser → FastAPI → LocalStack | Browser uploaded `tests/fixtures/ses-final-preparation.csv` using the synthetic-demo checkbox; direct transfer reached 100% | PASS |
| Upload batch | `e2bedf66-caa7-4a59-9d86-eabb0bbf732a`, `is_demo=true`, final ingestion state `processed` | PASS |
| Targeted S3 event → ingestion handler | One object-specific `ObjectCreated:Post` envelope; one accepted user, zero rejected rows | PASS |
| Matching-request outbox | `cf8954b7-c975-5f68-80d4-56a63f7c67c8`, delivered once using `dispatch_once(..., only_event_id=...)` | PASS |
| Workflow B | n8n execution `175`, terminal `success`; application run `86680840-0c33-4f42-9736-a49a87462398` succeeded | PASS |
| Match | Exactly one `potential` row, `34d554ac-98a7-46d5-adaa-3cb5dbc03ac1`, for current verified `SYNTHETIC DEMO — profile-only`; no official bank match | PASS |
| Completion outbox | `28468b63-316a-53e7-ac10-450ebba1c17c` is the **only** pending/processing event and belongs to the new batch | PASS |
| Notification | Zero rows for the new batch; no active `reserved` or `sending` notification. One logical intended notification is identified by the batch/user/template idempotency key | PREPARED, NOT RESERVED |
| Previous failed attempt | Existing notification remains `ambiguous`, `attempt_count=1`, no SES Message ID; no historical event replayed | PASS |
| Safe mode | `NOTIFICATION_MODE=test`, `NOTIFICATION_TRANSPORT=mock`, `NOTIFICATION_SES_ENABLED=0`, `NOTIFICATION_SES_MAX_ATTEMPTS=0`; dispatcher stopped | PASS |

The new user's internal UUID is `e067ea90-c557-4618-a7cd-e6789909097a`. The authorization key was recomputed with `services.notifications.content.idempotency_key(batch_id, user_id)` and matched the value stored **only** in ignored `.env` under `NOTIFICATION_SES_AUTHORIZED_IDEMPOTENCY_KEY`; it is deliberately omitted here. `NOTIFICATION_SES_AUTHORIZED_BATCH_ID` names the new batch. `.env` remains ignored with mode `0600`. The earlier unrelated `uploaded` demo batch was left untouched by targeting only the new S3 object.

## Handoff for a separately authorized single send — do not run during preparation

1. Obtain explicit authorization for the actual AWS SES attempt. Recheck that n8n's **published** Workflow C still references the stored AWS credential in `eu-north-1`, with preflight `sender` and `recipient` expressions. The owner has attested that the access key belongs to the restricted `loan-eligibility-ses` IAM user; no IAM call was made here.
2. Recheck this batch has one user, one potential match to one synthetic product, no notification record, and that completion event `28468b63-316a-53e7-ac10-450ebba1c17c` is the **only** due event. Stop if any unrelated event or dispatcher appears. Never replay the previous ambiguous notification.
3. In ignored `.env` only, preserve the controlled sender/recipient and existing scoped authorization values; change only `NOTIFICATION_TRANSPORT=ses`, `NOTIFICATION_SES_ENABLED=1`, and `NOTIFICATION_SES_MAX_ATTEMPTS=1` (keep `NOTIFICATION_MODE=test`). Run `make config`, then refresh the private helper with `docker compose --project-directory . --env-file .env -f infrastructure/docker-compose.yml up -d --no-deps --wait discovery`. Verify its effective mode without printing identities or credentials.
4. Dispatch **only** the completion event with this one-shot command. Do **not** use unscoped `make matching-dispatch` or `--watch`. Signed delivery should start Workflow C, reserve one notification, pass recipient preflight, and permit at most one SES-node attempt. Do not automatically retry if the dispatcher reports an error.

   ```bash
   uv run --frozen --env-file .env python -c 'import uuid; from services.common.db import make_engine; from services.eligibility.dispatcher import dispatch_once; engine=make_engine(); print(dispatch_once(engine, only_event_id=uuid.UUID("28468b63-316a-53e7-ac10-450ebba1c17c"))); engine.dispose()'
   ```
5. Inspect Workflow C's terminal execution **and SES node result**. Record any SES API response and Message ID; acceptance is not inbox delivery. Independently inspect the controlled Inbox and Spam folder and confirm the synthetic disclaimer. If the provider outcome is missing or uncertain, leave the notification `ambiguous` and stop without another send.
6. Regardless of outcome, stop any dispatcher, restore `NOTIFICATION_TRANSPORT=mock`, `NOTIFICATION_SES_ENABLED=0`, and `NOTIFICATION_SES_MAX_ATTEMPTS=0` in ignored `.env`; clear both `NOTIFICATION_SES_AUTHORIZED_*` values, refresh `discovery`, and verify no unexpected pending sends. Do not reset, delete, or replay either ambiguous record.

The prepared batch is **not** evidence of SES acceptance or a received email. The tracked workflow export is credential-free; the currently published local workflow was verified separately. The earlier SES-node configuration failure is recorded in `docs/aws-ses-live-evidence.md` and remains historical evidence.
