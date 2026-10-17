# Controlled SES attempt — 2026-10-16

## Latest SES outcome — PASS, execution 185 (2026-10-17 10:26 UTC)

One separately authorized attempt was accepted by AWS SES in `eu-north-1`. The controlled Gmail recipient confirmed receipt with the synthetic product label and required disclaimer. Notification state is `sent`, attempt count **1**, with a persisted provider Message ID. Mock transport is restored, SES disabled, maximum attempts zero, scoped authorization cleared, and dispatcher stopped. Five historical ambiguous notifications are unchanged. See [successful delivery evidence](aws-ses-success-evidence.md).

This supersedes historical failed-attempt summaries below. Live SES sending and owner-confirmed receipt are **PASS**; a received-email screenshot/video has not yet been supplied. Live Gemini use, evaluator access, demonstration video, and submission remain incomplete. The project is not fully submission-ready.

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

The owner later configured the local recovery token. A fresh read-only check found the exact key and record state valid, but the agent's visible-terminal control could not open the private `getpass` prompt (`Unable to determine Orca.app path from symlink: /usr/local/bin/orca`). The token was not read or piped from `.env` to bypass the prompt. **The recovery command was not run**; event `28468b63-316a-53e7-ac10-450ebba1c17c` is still `delivered`, no preparation audit row or far-future hold exists, and neither notification was changed. No Workflow C execution, AWS request, or email send occurred in this preparation attempt.

## One authorized targeted SES attempt after recovery release — 2026-10-16

**FAIL — no email received.** This section supersedes the earlier *historical* pre-release state above. The owner separately prepared and released the same event, then authorized **one** final real SES attempt and reconfirmed that account safeguards covered ₹0 out-of-pocket cost. No additional AWS resource was created, and no second send was attempted.

| Boundary | Sanitized observation | Result |
|---|---|---|
| Exact recovery scope | Batch `e2bedf66-caa7-4a59-9d86-eabb0bbf732a`, event `28468b63-316a-53e7-ac10-450ebba1c17c`, notification `d27db780-33fd-47a3-a13e-d4579d3bb7f7`, preparation audit `f05e5449-5987-46e1-b0b1-54478b572a51`, release audit `a3da1020-0d39-4f0b-9c89-9ea1ff67c52d`. One verified **synthetic** potential match, no real-bank match, no unrelated pending completion event. | PASS |
| Published n8n configuration | Active Workflow C version `ca115f84-8244-4d83-9739-d830a00f09da` had the stored AWS credential bound; its locally checked credential region was `eu-north-1`. SES `email/send` used preflight sender, recipient, subject and HTML expressions, with `retryOnFail` absent. Sender and recipient matched the same non-placeholder controlled identity; addresses are omitted. | PASS |
| Activation | Only ignored `.env` was set to test/SES/enabled/one attempt with the exact batch and key. Compose expansion and the running helper were checked for exact key equality without printing it. An initial helper recreate used the wrong Compose project directory and failed before any dispatch; mock mode was restored, then the helper was recreated with `--project-directory .` and verified healthy before reactivation. | PASS after local startup correction |
| Targeted dispatcher | One call to `dispatch_once(..., only_event_id=28468b63-316a-53e7-ac10-450ebba1c17c)` returned `delivered`, meaning durable n8n webhook acceptance only. The event has two lifetime claims (the original failed run and this recovery) and retains `targeted_only`; no unscoped dispatcher was started. | PASS |
| Workflow C | Execution **177**, terminal n8n `success`, duration **1,218 ms**, last node **Notification Execution Summary**. Overall success reflects handled node errors, **not** successful email delivery. | PASS for terminal execution; FAIL for send |
| AWS SES node | Executed once. Its `continueRegularOutput` item contained the sanitized error **“Forbidden - perhaps check your credentials?”**. No SES Message ID or accepted-send response was present. This is consistent with an authorization rejection, but the precise provider/IAM cause was not established without further AWS calls. No automatic retry was configured or performed. | FAIL |
| Notification record | Original reservation preserved; `delivery_mode=ses`, `status=ambiguous`, `attempt_count=1`, no Message ID, error code `ses_node_error_or_timeout`. The prior ambiguous notification remains at one attempt and without a Message ID. Do not retry either record. | PARTIAL |
| Controlled inbox | Owner checked Inbox and Spam and explicitly reported **not received**. No received-email screenshot exists. | FAIL |
| Mandatory rollback | Ignored `.env` and healthy helper returned to test/mock/SES-disabled/zero-attempt mode; both scoped authorization values were cleared. Dispatcher stopped; no unrelated pending notification events. Historical records and error evidence remain intact. | PASS |

The node's generic `Forbidden` response is evidence of a failed SES-node request, **not** SES acceptance. The exact IAM/SES rejection cause remains unverified; do not infer one from this message or make another send without new authorization. No actual received-email requirement is satisfied by this run.

## Read-only execution-177 rejection diagnosis

The saved SES-node output contains only `Forbidden - perhaps check your credentials?`. The execution record does **not** retain a numeric HTTP status, AWS error code or message, request ID, endpoint hostname, or signature diagnostic. The n8n container logs for the execution window supplied no additional error. The workflow reached its terminal `success` summary because the SES node continued on error; this is not a successful send.

Read-only inspection matched execution 177's workflow version to the published active version. That version references the stored AWS credential on its SES `email/send` node. The credential has nonempty access-key fields and region `eu-north-1`; its stored fields contain no custom endpoint or role-assumption configuration. Key material and addresses were not displayed. The installed n8n SES node calls the SES **`SendEmail`** action, not `SendRawEmail`. The request's actual resolved hostname is not present in the execution record, so endpoint selection cannot be independently proved from this evidence.

No live IAM policy, account ID, identity ARN, permissions boundary, organization policy, or SES identity status is stored in the repository. The IAM principal and verified sender/recipient remain owner-attested; neither was independently checked against AWS in this investigation. Consequently the precise cause cannot be distinguished among a missing/conditional `ses:SendEmail` permission, an incorrect identity ARN or account, an overriding deny/boundary/SCP, invalid signing credentials, or an SES account/identity restriction. `Forbidden` alone does not establish which one occurred. There is no evidence that `ses:SendRawEmail` is required for this node.

**Next safe diagnostic:** an authorized account administrator should inspect the restricted user's effective policy and the corresponding AWS-side request error (for example, a sanitized CloudTrail event or console error) **without sending another email**. Check `ses:SendEmail` on the verified identity ARN in `eu-north-1`, the exact `ses:FromAddress` and `ses:Recipients` conditions, explicit denies, permissions boundaries, and organization policies; separately confirm the identity and account sending status in that Region. A sanitized error code/message and request ID, plus redacted policy statements and identity ARN/account/Region alignment, are needed before a specific correction can be recommended. Preserve least privilege and the controlled-recipient condition; do not attach broad SES permissions as a diagnostic shortcut. No AWS configuration was changed, and neither ambiguous notification may be retried under this investigation.

## Fresh synthetic batch: one authorized targeted attempt — 2026-10-17

**FAIL for SES acceptance and inbox receipt.** This is a separate, new synthetic batch. The owner authorized one sending attempt. The owner reported an IAM Policy Simulator result of ALLOWED for the controlled recipient and DENIED for an unauthorized recipient; this run did not independently call IAM. No second dispatch or SES retry occurred.

| Boundary | Sanitized observation | Result |
|---|---|---|
| Final preflight | Batch `adcf1f84-f6b6-4dad-9010-c613c037553f` was matched with one accepted synthetic user, zero rejected rows, one deterministic potential match to an explicitly synthetic product, and no real-bank match. Completion event `ec5a0972-60b1-5107-b136-45437c7e55e5` was pending with retry count zero; it was the only pending completion event. No notification reservation or SES attempt existed for this batch. Historical ambiguous records were unchanged. | PASS |
| Published n8n configuration | Active Workflow C version `ca115f84-8244-4d83-9739-d830a00f09da` had a stored AWS credential bound with locally checked region `eu-north-1` and no endpoint override. The `email/send` node used preflight sender, `={{ [$json.recipient] }}`, subject and HTML body; it had no node retry or alternate recipient. Sender and recipient were the same non-placeholder controlled identity, distinct from the CSV address. | PASS |
| Scoped activation | Ignored `.env` was temporarily test/SES/enabled/one attempt, retaining the exact batch and recomputed notification key. The private helper was refreshed with the canonical Compose project and its effective settings checked. No background dispatcher ran. | PASS |
| Exact-event dispatch | One call to `dispatch_once(..., only_event_id=ec5a0972-60b1-5107-b136-45437c7e55e5)` returned `delivered`, meaning durable webhook acceptance. The event is now `delivered` with one claim; it was not replayed. | PASS |
| Workflow C | Execution **179**, published version above, started **08:13:25.532 UTC** and stopped **08:13:28.843 UTC** (3.311 s), terminal `success`; last node **Notification Execution Summary**. | PASS for terminal execution only |
| AWS SES node | Ran once (2.875 s). Its only output item contained **“Bad request - please check your parameters”**. No SES Message ID, accepted-send response, numeric HTTP status, AWS error code, or request ID was retained in the saved output. Terminal workflow success reflects the handled error. | FAIL for acceptance; exact provider cause NOT_VERIFIED |
| Notification database | New row `0b962461-d315-40b3-bff0-085772a387af`: `delivery_mode=ses`, `status=ambiguous`, `attempt_count=1`, no Message ID, error code `ses_node_error_or_timeout`. The associated application workflow record is `succeeded` with one ambiguous outcome and zero sent. Both earlier ambiguous rows remain at one attempt with no Message ID. | PARTIAL; preserve ambiguity |
| Controlled inbox | Owner checked the verified Gmail Inbox and Spam and confirmed **no email received**. No received-email screenshot exists. | FAIL |
| Mandatory rollback | Ignored `.env` and healthy helper returned to test/mock/SES-disabled/zero-attempt mode; both scoped authorization values were cleared. Dispatcher stopped and no completion event remains pending. | PASS |

The node's generic error does not expose the underlying SES or AWS validation reason. There is no evidence of provider acceptance or receipt. Do not retry this notification, clear its ambiguity, or reuse the event. The received-email assignment requirement remains unmet.

### Read-only diagnosis of execution 179 — 2026-10-17

The saved n8n execution contains exactly one run of the SES node and one output item: `error: "Bad request - please check your parameters"`. It contains **no** HTTP status field, AWS error code or description, request ID, endpoint, or raw request. In the installed n8n 2.43.5 `NodeApiError` implementation, that exact generic text is the mapping for HTTP **400**; the actual status was not retained in execution 179, so HTTP 400 is a strong inference, **not** independently confirmed response metadata. The published workflow remains active at version `ca115f84-8244-4d83-9739-d830a00f09da`; no workflow or database record was changed in this diagnosis.

The saved output of `Enforce Test Recipient and Begin Attempt` has nonempty, trimmed **strings** for sender, recipient, subject (31 characters), and HTML (447 characters). Both address fields have a single-address shape and equal the configured controlled identity; their values are omitted. The earlier compose node had `sender=null` before preflight, but the preflight output passed to SES contained a valid sender string. No null, nested array, or sample CSV address reached the SES input. The credential's stored region remains `eu-north-1` and has no endpoint override; the request's actual endpoint was not recorded.

The published SES node is `n8n-nodes-base.awsSes` version **1**, `resource=email`, `operation=send`, with the stored AWS credential bound. Its sender, recipient, subject, and body expressions use the preflight fields; `isBodyHtml=true`, `additionalFields={}`, and node retry is absent. The installed n8n expression engine evaluated the **actual saved** preflight data offline: sender, subject, and body became strings; `={{ [$json.recipient] }}` became exactly one string in a flat array. Thus the recipient expression's type and nesting do **not** explain the observed rejection.

The installed node builds a classic SES `SendEmail` query with `Action`, `Source`, `Destination.ToAddresses.member.1`, `Message.Subject.Data`, `Message.Body.Html.Data`, and `Message.Body.Html.Charset=UTF-8`. Its inspected code does **not** add `Version`, and the local AWS signing helper does not add it either. [AWS SES common parameters](https://docs.aws.amazon.com/ses/latest/APIReference/CommonParameters.html) mark `Version` required; the classic API version is `2010-12-01`. This is a **confirmed local request-contract discrepancy** and a plausible cause of a 400-class response. It is **not a confirmed root cause for execution 179** because the saved result omits the AWS error code and message; other validation failures could produce the same generic n8n text. The installed built-in node has no workflow parameter for adding `Version`, so no safe project-level parameter edit can correct it while retaining this SES node. The published workflow was not patched or republished.

Offline regression checks in `tests/notifications/test_ses_contract.py` validate the export and published parameter shapes, evaluate the recipient expression with the installed n8n engine, validate intended `SendEmail` types and required fields with Botocore's local service model, reject malformed controlled-recipient configuration, and verify synthetic content and CSV-address isolation. **19 new tests passed**; the full notification/recovery suite passed **63/63** without invoking SES, Workflow C, or AWS. Botocore's shape validator does not prove SES identity verification or that nonempty text will be accepted by the service.

Before any separately authorized future send, obtain a sanitized AWS-side error code/message or request trace for execution 179 if available; verify a corrected n8n SES node includes all required classic API parameters in an offline request capture; then review and publish the corrected workflow. Preserve the three ambiguous notifications and their one-attempt counts. No retry of event `ec5a0972-60b1-5107-b136-45437c7e55e5` is authorized by this diagnosis.

### Offline final-request capture — 2026-10-17

A separate `n8nio/n8n:2.43.5` container with networking disabled ran the installed SES node and AWS signer using synthetic credentials and `.test` addresses. The final intercepted request was `POST` to the regional classic SES endpoint, with SigV4 scope `eu-north-1/ses/aws4_request`. It contained `Action=SendEmail`, `Source`, one `Destination.ToAddresses.member.1`, subject and UTF-8 HTML parameters in the URL query. **The final signed request did not contain `Version`.** A one-line, version-pinned patch applied only in the offline harness added `Version=2010-12-01` and retained exactly one recipient. The live n8n installation and published Workflow C were **not** modified or executed.

The missing `Version` is a confirmed local discrepancy with the [classic SES common-parameter contract](https://docs.aws.amazon.com/ses/latest/APIReference/CommonParameters.html), but **the root cause of execution 179 remains NOT_VERIFIED** because its saved error lacks the AWS code, message and request ID. The captured node also used a query-only POST with no body or `Content-Type`; SES acceptance of that format was not established offline. See [the request-contract audit](aws-ses-request-contract.md) for the complete trace, patch, offline tests and rollout prerequisites. No further SES attempt, Message ID or inbox receipt occurred during this audit.

### Offline transport completion — 2026-10-17

The follow-up [request-contract audit](aws-ses-request-contract.md) established the documented AWS Query POST format using the AWS-authored Smithy protocol and installed Botocore SES model. The patch now supplies Action and Version in a form-encoded body, with Content-Type and Content-Length, and avoids JSON quoting in the SES helper. A network-disabled derived-image capture verified one recipient and independently verified SigV4 over the transmitted body and headers; body or Content-Type tampering invalidates the signature. This supersedes the earlier version-only patch and unresolved transport-format assessment. AWS tolerance of the original query-only POST and the exact rejection reason for execution 179 remain unverified.

All 129 selected notification, recovery, matching/dispatcher, database integration and unit tests passed. Ruff, mypy, workflow JSON and Compose validation passed. The recovered test failure was reproduced by a one-second dispatcher-clock lag and repaired by explicitly making its fixture event due; production isolation is unchanged. The derived image was built locally but **not deployed**. The original n8n remains healthy, Workflow C is still version `87b22acd-4324-40bd-94f2-6564255589a6`, latest execution remains 179, and three SES records remain ambiguous with one attempt and no Message ID. Both configuration and running helper remain test/mock/SES-disabled/zero-attempt, with no dispatcher. No email, AWS call or new notification attempt occurred.

### Authorized local patch deployment — 2026-10-17T09:18:20+00:00

**PASS — local n8n image replacement completed; no email or workflow execution.** The retained original n8n 2.43.5 image was replaced locally with tested immutable image `sha256:3897004d6718a62a9d9e0d1e3656911690567e1f077e85fdc2dec6ce74caa04a`, now healthy. Verified database, volume and encryption-key/configuration backups were stored outside Git before replacement. The [local rollout record](aws-ses-request-contract.md#authorized-local-rollout) documents original/patched images, backup integrity, the persistent private Compose override and rollback instructions.

Before/after fingerprints confirm preservation of encrypted credentials, workflow definitions/history and all 40 execution records. A final direct comparison of owner fields with the backup found only `updatedAt` changed during runtime; password, identity and all other fields are preserved. Workflow C remains published at `87b22acd-4324-40bd-94f2-6564255589a6`; credential binding/decryptability, region `eu-north-1`, HMAC/preflight, one recipient and disabled retries are preserved. Latest execution remains 179. Application records are unchanged; three SES notifications remain ambiguous with one attempt and no Message ID. Configuration and helper remain test/mock/SES-disabled/zero-attempt; dispatcher remains stopped.

Installed patch and file hashes match the tested image. The network-disabled synthetic request capture validates the form body, API Version, recipient and SigV4 signature. Fresh post-rollout contract tests: **40 passed**. No AWS API call or new SES attempt was initiated. Real provider acceptance and inbox receipt remain NOT_VERIFIED. Rollback was not needed; the original image is retained. This rollout does not authorize sending or historical replay.


## Patched-image controlled attempt — execution 181

Date: 2026-10-17. Owner authorized exactly one attempt for replacement batch `6fd3d3f1-6520-4c7d-9dab-141b152ac814` and completion event `747daee0-0fdc-554f-ab0b-07db40af6519`.

- Final preflight verified one accepted synthetic user, one synthetic potential match, event pending with retry count 0, no reservation, scoped authorization match, controlled recipient isolation, no unrelated pending completion, and unchanged historical records.
- Published C version `87b22acd-4324-40bd-94f2-6564255589a6` retained one recipient, preflight expressions, HMAC, stored AWS credential in eu-north-1, and no automatic SES node retry.
- Running image: `sha256:3897004d6718a62a9d9e0d1e3656911690567e1f077e85fdc2dec6ce74caa04a`.
- A local control-script dictionary lookup error initially stopped execution before dispatch. Exception-safe cleanup restored mock mode. The error was corrected, the event and absent reservation rechecked, and authorization restored before the sole dispatch. This did not execute Workflow C or consume an SES attempt.
- Scoped activation used test/SES/enabled/maximum attempts 1. Only the internal helper was refreshed with the canonical Compose project and saved image override; n8n was not recreated.
- Exactly one event-specific dispatch returned `delivered`. Event is now delivered, retry count 1.
- Workflow C execution **181** started `2026-10-17 09:34:14.175 UTC`, ended `09:34:15.263 UTC` (1.088 seconds), terminal status success; last node `Notification Execution Summary`.
- Saved SES node evidence contains exactly one node run and one output: `error: "Bad request - please check your parameters"`. No Message ID, HTTP status, AWS error code, or request ID was retained. Do not infer provider acceptance from terminal workflow success.
- Notification `514f933f-277e-43e3-88e1-2284519bd1dc`: ambiguous, attempt count 1, no SES Message ID, diagnostic code `ses_node_error_or_timeout`.
- Mandatory rollback verified ignored `.env` and healthy helper in test/mock, SES disabled, maximum attempts 0, both scoped values cleared. No dispatcher or pending completion event remains.
- Post-attempt fingerprints confirm previous notification records and recovery audits unchanged, published workflows unchanged, and exactly one new Workflow C execution. No second send or dispatch occurred.
- Owner checked the controlled inbox and reported **No email received**. Actual SES acceptance/delivery requirement remains incomplete.

The offline patch verification does not explain this live rejection. Its exact cause remains unverified because the saved node output omits provider diagnostic fields. Further investigation must be read-only/offline; no replay, attempt reset, or additional send is authorized.

Fresh post-attempt checks: 85 notification tests passed (including offline SES contract, recipient isolation, HMAC, attempt-limit, idempotency, recovery, and published parameter checks); Ruff and Mypy passed (53 source files), and `git diff --check` passed. Tests did not invoke live SES.

## Diagnostic image successfully deployed locally — no send

On 2026-10-17, after separate authorization and fresh verified backups, the retention-aware rollout succeeded. n8n now runs `sha256:7a6c3576b77f302b0ba1c13bb9de2ea2687487a52c5466a99dd6d248ff4586e2`. All seven current workflow history rows survived unchanged; no retention exception was needed. Published workflows, credentials, execution records and application records are preserved. The owner-record comparison allowed only its runtime `updatedAt` timestamp. See [diagnostic rollout evidence and current override](aws-ses-safe-diagnostics.md#authorized-retention-aware-retry--pass).

The installed image retains only allowlisted status/code/request-ID diagnostics on a future handled SES failure. It cannot recover the missing AWS details from execution 181 and does not establish that SES sending is fixed. Latest C execution remains 181; four one-attempt ambiguous notifications remain unchanged. SES remains disabled in mock mode, scoped authorization is empty, and no dispatcher or pending completion event exists. No email or live workflow execution occurred during rollout. Another send requires separate explicit authorization and fresh isolated preparation.


## Diagnostic-image single attempt — execution 183

The owner explicitly authorized exactly one SES test email. The earlier pasted preparation referred to an already-consumed batch; it was not reused. The current fresh batch and event were identified before execution.

| Evidence | Result |
| --- | --- |
| Date / region | 2026-10-17 / eu-north-1 |
| Authorized fresh batch | `6b524d02-204b-4b0a-b0e2-6ad260adf4d9` |
| Sole dispatched event | `cbe2a3c8-d458-5781-8384-d6e8949d67e1` |
| n8n execution | `183`, terminal success with handled SES rejection |
| Published C version | `87b22acd-4324-40bd-94f2-6564255589a6` |
| Start / finish UTC | 09:58:41.104 / 09:58:42.254 (1.150 seconds) |
| SES node runs | Exactly one |
| Final node | Notification Execution Summary |
| Saved generic error | SES request failed; inspect safe diagnostics |
| HTTP status | **400**, captured diagnostic |
| AWS error code | **MessageRejected**, captured diagnostic |
| AWS request ID | `27ff80c4-8694-49f5-bdab-7356ef54d0cb` |
| SES Message ID | None; request ID is not an acceptance Message ID |
| Notification | `19afd6e5-68b6-429c-afcd-8dc036c24473` |
| Notification status / attempts | ambiguous / 1 |
| Application diagnostic | ses_node_error_or_timeout |
| Outbox event status / claim count | delivered / 1 |
| Pending completion events afterward | 0 |
| Inbox receipt | Owner confirmed **No email received** |

Preflight verified a healthy canonical diagnostic image, the exact pending event at retry count zero, one synthetic user/match, no prior reservation, scoped key match, controlled identity isolation, unchanged historical notifications and published recipient/preflight/HMAC configuration. Only the helper was refreshed for temporary test/SES/enabled/one-attempt mode. Only the authorized event was dispatched once; no background dispatcher was started.

Exception-safe cleanup restored ignored `.env` and healthy running helper to test/mock, SES disabled, maximum attempts 0, both scoped values cleared. The diagnostic n8n image was not replaced. Post-attempt fingerprints verified the previous four notification records, recovery audits and published workflows unchanged. Exactly one new Workflow C execution and one new notification attempt exist. No retry, attempt reset or replacement notification occurred.

The diagnostic patch successfully preserved the status, provider error code and request ID. It deliberately did not save the provider's potentially sensitive message, so the specific reason within MessageRejected remains unverified. Do not claim that this code establishes an unverified identity, sandbox problem, IAM problem or request-serialization defect. No further AWS operation or send is authorized. Preserve this ambiguous record.

Fresh post-attempt verification: **88 notification tests passed** with offline diagnostic/contract capture against the diagnostic image. Ruff and Mypy passed (54 source files); `git diff --check` passed. No live SES send was invoked by tests.
