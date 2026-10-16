# Controlled SES attempt — 2026-10-16

Status: **PARTIAL**. The application reached the real n8n AWS SES node exactly once, but n8n rejected the node locally with `Node does not have any credentials set`. There is **no SES API response or SES Message ID**. The owner independently checked the controlled Inbox and Spam folder and reported **not received**. Do not present this as a delivered email or retry the ambiguous notification without separate authorization.

## Scope and procedure

- Region configured in the stored n8n AWS credential: `eu-north-1` (checked locally without displaying key material). The sender and controlled recipient were equal, non-placeholder values; neither address is recorded here. The AWS account's verification status was supplied by the owner, not checked with an AWS API.
- Before activation: test mode, mock transport, SES disabled, one-attempt limit zero, no dispatcher, no pending outbox event, and no earlier SES attempt. The SES node's **draft** referenced the stored AWS credential and used the preflight `sender` and `recipient` fields.
- Set only ignored local `.env` switches to SES enabled and one-attempt limit `1`; recreated the internal helper and confirmed those settings. No credentials or HMAC settings changed.
- Seeded existing clearly synthetic fixtures. A browser uploaded a one-row CSV through FastAPI and LocalStack; the local ingestion worker accepted one user with no rejected rows. The first fixture used an invalid reserved-domain email and was rejected before any outbox event; it was corrected to a valid reserved example-domain fixture and committed separately. No CSV address was used for notification delivery.
- Sanitized accepted batch: `cf6714c4…bcbc1`. Immediately before matching, its upload-ready event was the **only** pending event. Signed dispatcher delivered it to n8n Workflow B. The batch produced exactly one `potential` match to `SYNTHETIC DEMO — profile-only`, not a real lender offer. Its completion event was again the only pending event before the one authorized Workflow C dispatch.

## Actual execution evidence

| Boundary | Observed result | Status |
|---|---|---|
| Browser → FastAPI → LocalStack → ingestion → PostgreSQL | One accepted synthetic user, zero rejected rows, one upload-ready event | PASS |
| Workflow B | n8n execution **173**, terminal `success`, 3,331 ms; one synthetic potential match | PASS |
| Completion outbox → Workflow C | Signed event accepted; n8n execution **174**, terminal `success`, 303 ms | PASS |
| Notification preflight | One reserved notification became `sending`; `attempt_count=1` | PASS |
| AWS SES node | Ran once but returned `Node does not have any credentials set`; no provider response or Message ID | FAIL |
| Notification database | One row, `delivery_mode=ses`, `status=ambiguous`, `attempt_count=1`, no SES Message ID; error code `ses_node_error_or_timeout` | PARTIAL |
| Controlled inbox | Owner checked Inbox and Spam and reported **not received**; no email screenshot exists | FAIL |
| Rollback | Helper healthy in `mock` mode, SES disabled, one-attempt limit zero; dispatcher stopped; no pending/processing outbox events | PASS |

The application marks the result ambiguous because the SES node's `onError=continueRegularOutput` path records a missing provider ID conservatively. The node's specific error indicates that this attempt did **not** reach a usable AWS credential. n8n marked the workflow execution successful because the error was handled; that status is not email-delivery evidence.

## Root cause and recovery boundary

Read-only comparison after the attempt found that the workflow **draft** had the AWS credential reference, but the **published active version** and execution 174 snapshot had **no SES credential reference**. The draft also lacked explicit SES `email/send` parameters and held a different recipient parameter shape. Thus the preflight review of the draft was insufficient. This run's ambiguous notification record and attempt count must remain intact; do not clear them or replay this event to force a resend. The one-attempt gate also prevents another SES preflight in this local database without an explicit, reviewed reset or new policy.

## Configuration repair — no send (2026-10-16)

- Confirmed the original workflow ID `loanNotificationsM6` had a draft SES credential reference to stored n8n AWS credential `W656hx0hT7mFU3vm`, while published version `24d798a5-d731-4b8b-affe-1087afc4b099` had none. The stored credential is type `aws`; a local decrypted-field check confirmed region `eu-north-1` without displaying key material. Its n8n display name is generic, so the precise IAM principal remains owner-attested and cannot be independently verified without an AWS identity call (not authorized for this repair).
- Reimported the checked-in Workflow C definition **into the same workflow ID**, attaching that existing credential reference only in the local import stream. This restored `resource=email`, `operation=send`, sender `={{ $json.sender }}`, and recipient `={{ [$json.recipient] }}` while retaining the signed internal steps, event acknowledgement, preflight, mock branch, and duplicate-send controls. The tracked `workflows/notifications.json` remains intentionally credential-free and portable; importing it alone will require a local credential rebind and publication.
- Published the repaired workflow and restarted n8n without triggering a webhook. Read-only inspection of active version `ca115f84-8244-4d83-9739-d830a00f09da` found the same AWS credential reference and correct SES parameters. n8n `/healthz` returned HTTP 200. No Workflow C execution or AWS request was made during this repair.
- Verified ignored local configuration remains `NOTIFICATION_MODE=test`, `NOTIFICATION_TRANSPORT=mock`, `NOTIFICATION_SES_ENABLED=0`, and `NOTIFICATION_SES_MAX_ATTEMPTS=0`; sender and controlled recipient still match and are non-placeholder values. The dispatcher is stopped, there are zero pending/processing outbox events, and the earlier notification is still `ambiguous` with `attempt_count=1` and no SES Message ID. No new SES notification row exists.
- A future live test requires separate authorization, a **new** synthetic batch and notification reservation, and a fresh preflight. This repair does not prove AWS acceptance or inbox delivery; the assignment's received-email requirement remains unmet.

No AWS infrastructure was created, no unrelated AWS API operation was performed, and no additional SES send was attempted. This evidence does not satisfy the assignment's received-email demonstration requirement.

## Second isolated authorization — 2026-10-16

Status: **FAIL before SES / no AWS request**. The owner explicitly confirmed that account safeguards still covered one attempt within the ₹0 out-of-pocket limit. The one authorized completion event was dispatched exactly once; it reached Workflow C, but the notification preflight returned HTTP 422 before the AWS SES node. There was **no SES API response, Message ID, or recorded SES send attempt**. Inbox receipt was not independently checked for this run and is **NOT_RUN**; do not infer delivery.

| Boundary | Observed result | Status |
|---|---|---|
| Final local preflight | Batch `e2bedf66-caa7-4a59-9d86-eabb0bbf732a` had one accepted synthetic user, one potential synthetic match, one pending completion event `28468b63-316a-53e7-ac10-450ebba1c17c`, no existing reservation, and no unrelated pending notification event. Published Workflow C used stored AWS credential `W656hx0hT7mFU3vm` configured for `eu-north-1`; sender/recipient expressions came from preflight. Sender and controlled recipient matched; their values are omitted. | PASS |
| Scoped local activation | Ignored `.env` was set to test/SES/enabled/one attempt; the private helper restarted healthy and reflected those switches. No background dispatcher ran. | PASS |
| Targeted signed dispatch | `dispatch_once(..., only_event_id=28468b63-316a-53e7-ac10-450ebba1c17c)` returned `delivered`, meaning durable webhook acceptance, **not** completed notification. The event is `delivered` with one dispatch claim. | PASS |
| Workflow C | n8n execution **176**, terminal `error`, from 10:35:20.903 to 10:35:21.284 UTC (381 ms). Last node: **Enforce Test Recipient and Begin Attempt**. Its internal preflight request returned HTTP 422 `notification_step_rejected`. | FAIL |
| SES node / provider | SES node was **not reached**. No AWS request, SES response, or Message ID was observed. | NOT_RUN |
| New notification | Reservation `d27db780-33fd-47a3-a13e-d4579d3bb7f7` remains `reserved`, `attempt_count=0`, no Message ID. The application notification run remains `running` because the n8n error interrupted its completion path. No attempt was reset or retried. | PARTIAL |
| Earlier notification | Original notification `1b8173e7-efcc-4f7a-ace5-013a964ff92d` remains `ambiguous`, `attempt_count=1`, with no Message ID. | PASS |
| Mandatory rollback | Ignored `.env` and healthy helper returned to test/mock/disabled/zero; both scoped authorization values were cleared. Dispatcher is stopped. No outbox event is pending or processing. The new `reserved` row is preserved for investigation. | PASS |

**Confirmed local root cause:** `infrastructure/docker-compose.yml` passes the SES mode, enabled switch, and attempt limit into the private `discovery`/notification helper, but omits `NOTIFICATION_SES_AUTHORIZED_BATCH_ID` and `NOTIFICATION_SES_AUTHORIZED_IDEMPOTENCY_KEY`. Thus the helper could not see the authorization present in ignored `.env`; `compose(..., begin_send=True)` rejected it with `ses_authorization_unconfigured` (inferred from the inspected configuration and gate code; the API deliberately exposes only the generic 422 response). The published credential binding was not the failing boundary this time. Correct the Compose variable propagation and add a regression test before any separately authorized future run. Do **not** replay this event or retry the preserved reservation under the exhausted authorization.

This second dispatch does not satisfy actual SES sending or received-email requirements. No AWS resource was provisioned, and no real email was sent by this execution.

## Recovery implementation status — no live mutation (2026-10-16)

The Compose propagation defect was repaired and tested separately. A new event-specific, **no-send recovery preparation** now exists; see [the recovery review](aws-ses-recovery-review.md). It requires terminal n8n failure evidence showing no SES-node execution, a stale application run, an untouched `reserved` notification with `attempt_count=0`, exact event/batch/key authorization, and controlled-recipient/synthetic-match checks. Successful preparation would audit the action and place only that event on a far-future hold, **not** dispatch it.

This implementation was tested against isolated fixtures only. The live execution-176 event is still `delivered`, its notification remains `reserved` with zero attempts and no Message ID, and the earlier ambiguous notification remains unchanged. No live recovery, Workflow C execution, AWS request, or email send was performed while implementing the recovery operation. A separate authorization and reviewed release step remain necessary before any SES attempt.

On a subsequent live preparation request, the read-only safety checks again passed, but the operator recovery token was not configured. The existing deterministic key was staged only in ignored local configuration. **Preparation was not executed**: there is no new audit row or hold, the event remains `delivered`, and both notification records remain unchanged. This is an authorization blocker, not evidence of an attempted SES send or successful recovery.
