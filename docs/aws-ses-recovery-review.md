# Workflow C execution 176: recovery review

Review performed locally on 2026-10-16. **No Workflow C execution, dispatcher run, database repair, AWS request, or email send was performed.** All database inspection below was read-only; recovery behavior was exercised only against the dedicated notification test database.

## Observed state and failure boundary

| Record | Read-only observation |
|---|---|
| Authorized synthetic batch | `e2bedf66-caa7-4a59-9d86-eabb0bbf732a` |
| Completion outbox event | `28468b63-316a-53e7-ac10-450ebba1c17c`, `delivered`, `retry_count=1`, no last error |
| Application notification execution | `running`, heartbeat present, cursor unset |
| New notification | `d27db780-33fd-47a3-a13e-d4579d3bb7f7`, `reserved`, `attempt_count=0`, no SES Message ID, one linked synthetic match |
| Earlier notification | `1b8173e7-efcc-4f7a-ace5-013a964ff92d`, still `ambiguous`, `attempt_count=1`, no SES Message ID |
| Queue and dispatcher | Zero `pending`/`processing` events; dispatcher stopped |

n8n execution **176** ended `error` at **Enforce Test Recipient and Begin Attempt** (HTTP 422). Its saved `runData` contains that node and the earlier reservation/composition nodes, but **does not contain the AWS SES node**. Together with `attempt_count=0` and no Message ID, this is strong evidence that this *new* notification had no provider attempt. It does not change the earlier ambiguous notification's unresolved outcome. The 422 was caused by the previously repaired Compose omission of the two scoped authorization variables; the repair itself was verified separately in mock mode.

The signed dispatcher accepted HTTP 202 only after Workflow C's `/notifications/accept` step committed a unique application `workflow_executions` row. Workflow C's **Acknowledge Durable Notification Run** node responds before `/notifications/next`, `/notifications/compose`, `/notifications/preflight`, SES, and `/notifications/result`. `dispatch_once` therefore marked the outbox event `delivered` on **durable acceptance**, not successful processing or email acceptance. HMAC SHA-256, event ID/type, and a five-minute timestamp are checked by `/notifications/accept`; the unique event/run and notification idempotency keys prevent duplicate reservations. The later 422 did not retract the earlier 202.

This is a **reliability/observability gap, not evidence of a duplicate send**. Early acknowledgement is compatible with at-least-once delivery only if stalled accepted runs are monitored and recovered. `reconcile_stale` requeues a delivered event whose application run remains nonterminal and whose heartbeat is older than 15 minutes. `accept_event` then accepts the same run only when stale, and `next_reservation` returns the existing `reserved` notification. However, this recovery is coupled to the unscoped dispatcher loop. With that dispatcher stopped, no automatic repair occurs; a generic unscoped run could also touch unrelated events. An n8n error presently leaves the application run `running` rather than explicitly `failed`, delaying detection until the heartbeat expires. The outbox `delivered` label must not be represented as notification success.

## Recovery options

| Option | Benefit | Risk / prerequisite | Assessment |
|---|---|---|---|
| **A. Resume the existing reservation** | Reuses the same event, application run, notification ID, and unique idempotency key; no new notification is created. | Requires a reviewed **targeted** stale-run recovery, current evidence of zero provider attempts, corrected helper configuration, continued single-batch gate, and fresh authorization before SES mode. Never bypass `accept_event` or call preflight directly on live data for a probe. | **Recommended for execution 176**, but **not authorized or performed** by this review. |
| **B. Create a new synthetic batch** | Clean new event and gate for a separate demonstration. | Leaves execution 176's `reserved` row and `running` application run unresolved. If both batches are later resumed, the controlled inbox could receive two synthetic messages. It does not repair the acknowledgement gap. | Fallback only after an explicit decision to quarantine the old run without deleting or resetting evidence. |
| **C. Add explicit durable completion/failure acknowledgement** | Separates `accepted` from `completed`, records terminal workflow failures, enables targeted fenced recovery and alerting. | Requires a small protocol/schema and workflow change, migration or state-transition design, concurrency tests, and migration of existing runs; not a safe ad-hoc fix during an email test. | **Recommended systemic improvement** before unattended production dispatch. |

For option A, require a single-event recovery operation that locks and verifies the outbox event, application run, reservation, batch, match, and absence of provider attempt in one database transaction. It should requeue only this event under an exclusive/fenced claim, without altering the notification status or attempt count. A subsequent separately authorized, targeted dispatcher invocation would send a new HMAC-signed envelope; the same `accept_event` run and `next_reservation` path should be reused. The existing SES gate must still validate this exact batch and notification key. Stop if any state differs, if any unrelated event would be claimed, or if a provider outcome becomes uncertain. **This procedure is a design, not a command to run.**

## Isolated verification

- `uv run --frozen --env-file .env pytest -q tests/notifications tests/matching/test_matching.py`: **33 passed**. The new `test_stale_reserved_notification_reuses_reservation_without_sending` uses only the dedicated test database. It verifies that an immediate duplicate is rejected as a new run, a stale acknowledged event can be requeued, the same reservation is returned, the attempt count stays zero, exactly one notification exists, and its recipient remains the controlled test identity rather than the CSV address. It calls only `compose(..., begin_send=False)` for content preview; no SES node or provider is involved.
- Existing isolated tests additionally cover an interrupted `sending` record becoming `ambiguous` without resend, previous ambiguous-attempt isolation, invalid/missing batch or key rejection, one-attempt gate, concurrency, webhook authentication, and mock terminal states.
- `ruff` and `mypy` passed for the changed test file. Live record checks remained read-only. **No live recovery, terminal success, SES acceptance, or inbox delivery was tested.**

## Prerequisites before any future sending

1. Obtain separate explicit authorization for one SES attempt and reconfirm account spending safeguards and verified sender/recipient. No authorization from the earlier dispatch should be reused implicitly.
2. Decide and implement a **targeted**, audited recovery for execution 176; do not run the unscoped dispatcher against all stale events. Confirm the saved n8n execution still proves the SES node never ran and the new reservation remains `reserved`, `attempt_count=0`, without a provider ID. Leave the earlier ambiguous record untouched.
3. Recheck the published Workflow C credential/region, preflight recipient expressions, corrected Compose propagation, HMAC signing, scoped batch/key gate, absence of other due events, and that no dispatcher is running. Never print the recipient or key.
4. Only under that new authorization, enable SES for exactly one targeted attempt. Observe the n8n **terminal status and SES node result**, not merely the outbox `delivered` status. Preserve any ambiguous outcome; do not retry automatically. Restore mock mode immediately afterward.

Current readiness: **safe to plan a targeted recovery; not ready to send**. Actual AWS SES acceptance and inbox receipt remain unverified for execution 176.

## Implemented no-send recovery preparation (2026-10-16)

`services/notifications/recovery.py` now implements `prepare_recovery(...)`; `scripts/prepare_notification_recovery.py` is its explicit operator entry point. **Neither was run against the live application database in this milestone.** The operation requires the exact event UUID, batch UUID, notification idempotency key, n8n execution ID, and a separately entered 32+ character recovery token matching an environment-held token. It only operates in test/mock mode with SES disabled and attempt limit zero. The operator command prompts for the token without echoing it; the key is read from ignored local configuration, not a command-line argument.

In one application transaction it locks the exact delivered outbox row, the existing notification run, and its sole reservation. It requires a matched synthetic batch; a stale, still-running application execution with no cursor; one `reserved` SES-mode notification with `attempt_count=0`, no last attempt and no Message ID; the exact deterministic key; the configured controlled recipient rather than the CSV address; and exactly one linked verified synthetic potential match for one user. It reads the n8n database **read-only** and requires a terminal `error` for Workflow C, a failed preflight node, no SES-node run data, and the saved durable-acceptance output identifying the same application run and batch. Missing or pruned n8n evidence fails closed.

On success it creates a `workflow_executions` audit row of type `outbox_reconcile`, linked to the original notification run, recording the event, reservation and n8n execution IDs and prior dispatch count. It changes **only the named outbox event** to `pending` with `next_attempt_at=9999-12-31` and `last_error_code=manual_recovery_held`. That far-future hold means a running dispatcher cannot claim it merely because preparation occurred. It does **not** alter the notification, its attempt count, the original run, the previous ambiguous record, or any other event. Row locks serialize concurrent requests; a second request rejects because the event is no longer `delivered`. The audit row's `succeeded` status means **recovery preparation succeeded**, not notification delivery.

The new operator variables in `.env.example` default blank: `NOTIFICATION_RECOVERY_TOKEN` and `NOTIFICATION_RECOVERY_IDEMPOTENCY_KEY`. These are separate from the SES send gate and do not enable SES. A future operator must generate a fresh private token, fill these values only in ignored local `.env`, independently verify execution 176 and account safeguards, and obtain explicit authorization **before** running the following *preparation-only* command:

```bash
uv run --frozen --env-file .env python -m scripts.prepare_notification_recovery --prepare \
  --event-id 28468b63-316a-53e7-ac10-450ebba1c17c \
  --batch-id e2bedf66-caa7-4a59-9d86-eabb0bbf732a \
  --n8n-execution-id 176
```

The command prompts privately for the recovery token. It does not start a dispatcher, invoke Workflow C, release the hold, or send email. **Do not run it merely to check status.** A later SES attempt needs its own authorization plus a separately implemented/reviewed, event-specific **release of the hold** and targeted dispatch; no such release was performed or silently added here. Do not use unscoped `reconcile_stale` or manually edit the row without the corresponding safety checks. This preserves an intentional safety barrier between recovery preparation and sending.

Isolated verification: `tests/notifications/test_recovery.py` exercises valid preparation, incorrect event/batch/key, missing or wrong token, SES-started/ambiguous/provider-ID records, recent runs, missing or conflicting n8n evidence, CSV-recipient rejection, duplicate/concurrent requests, audit creation, unchanged reservation and attempt count, and unrelated-event preservation. Its n8n evidence is a minimal synthetic SQLite fixture; the application side uses the dedicated PostgreSQL test database. These tests do **not** demonstrate a live recovery or an SES send.

## Live preparation request — authorization pending (2026-10-16)

Read-only revalidation found execution 176 terminal `error`, its saved run data ending at preflight with no SES node, event `28468b63-316a-53e7-ac10-450ebba1c17c` still `delivered`, and notification `d27db780-33fd-47a3-a13e-d4579d3bb7f7` still `reserved` with zero attempts and no Message ID. The linked verified product is synthetic, the application run is stale, no unrelated notification event is pending, the dispatcher is stopped, and mock/SES-disabled/zero-attempt settings remain active. The deterministic key was derived from the live batch/user and staged only in ignored local `.env`; it is not recorded here.

**BLOCKED at operator authorization:** `NOTIFICATION_RECOVERY_TOKEN` is blank. The required private token was not generated, entered, or bypassed. Consequently the operator command was **not run**: no recovery audit row was created, the event was **not** placed on hold, and no live database record or n8n execution was modified. Resume only after the owner privately configures the token and can enter it at the command's non-echoing prompt; repeat all preflight checks immediately before invocation.
