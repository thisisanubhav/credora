# Controlled SES attempt — 2026-10-16

Status: **PARTIAL**. The application reached the real n8n AWS SES node exactly once, but n8n rejected the node locally with `Node does not have any credentials set`. There is **no SES API response, SES Message ID, or independently confirmed inbox receipt**. Do not present this as a delivered email or retry the ambiguous notification without separate authorization.

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
| Controlled inbox | Not independently confirmed; owner was asked to inspect Inbox and Spam | NOT_RUN |
| Rollback | Helper healthy in `mock` mode, SES disabled, one-attempt limit zero; dispatcher stopped; no pending/processing outbox events | PASS |

The application marks the result ambiguous because the SES node's `onError=continueRegularOutput` path records a missing provider ID conservatively. The node's specific error indicates that this attempt did **not** reach a usable AWS credential. n8n marked the workflow execution successful because the error was handled; that status is not email-delivery evidence.

## Root cause and recovery boundary

Read-only comparison after the attempt found that the current workflow **draft** has the AWS credential reference, but the **published active version** and execution 174 snapshot have **no SES credential reference**. Thus the preflight review of the draft was insufficient. The published version must be corrected and verified before any future separately authorized attempt. This run's ambiguous notification record and attempt count must remain intact; do not clear them or replay this event to force a resend. The one-attempt gate also prevents another SES preflight in this local database without an explicit, reviewed reset or new policy.

No AWS infrastructure was created, no unrelated AWS API operation was performed, and no additional SES send was attempted. This evidence does not satisfy the assignment's received-email demonstration requirement.
