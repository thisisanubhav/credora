# Fresh preparation after lowercase identity verification

Date: 2026-10-17. **Local preparation only; no SES send authorized or executed.**

## AWS-side evidence supplied by the owner

The owner confirmed creating a new lowercase email identity. Their console screenshot shows that identity Verified in eu-north-1. The account dashboard shows Healthy and sandbox mode. The supplied IAM policy screenshot allows SendEmail/SendRawEmail against the matching lowercase identity ARN in that region, with matching sender and restricted recipient conditions. These are owner-supplied console observations, not independently executed AWS API checks. No credential or workflow change was needed.

Earlier uppercase-only verification is a plausible explanation for the historical MessageRejected response, but its detailed provider message was not retained. Do not claim a proven sole root cause or successful sending before a separately authorized test.

## Prepared data

| Item | Verified value |
| --- | --- |
| Branch | `feat/aws-ses-fresh-test-preparation` |
| New batch | `5bac37d6-f3b2-435a-9341-48f465ae47ba` |
| Accepted / rejected | 1 / 0 |
| Matching request | `3dbda8bf-f096-5525-b621-ce9f11a5f82a` |
| Workflow B | `184`, terminal success |
| Potential matches | Exactly one, synthetic source; no real-bank match |
| Completion event | `8412f11b-8c63-55d7-9679-c39fc8efa128` |
| Completion state | Pending, retry count 0, undispatched |
| Global pending/processing completion events | Exactly one |
| Notification reservation / SES attempt for new user | None / zero |
| Published C | `87b22acd-4324-40bd-94f2-6564255589a6` |
| Latest C execution | Unchanged at 183 |
| Diagnostic n8n image | `sha256:7a6c3576b77f302b0ba1c13bb9de2ea2687487a52c5466a99dd6d248ff4586e2` |

The synthetic CSV row passed the real ingestion validator before upload. FastAPI issued the presigned LocalStack upload. The exact-object worker invocation returned a result differing from the private script's expected `processed` list; the script stopped before matching. A read-only database check independently established batch `processed`, one accepted user, zero rejection errors, and exactly one pending matching-request event. No second upload or ingestion invocation was made. The private ledger was completed from those verified records, and only that matching event was dispatched.

## Safety and preservation

The derived notification key is unique and matches the new batch and sole user. The two scoped authorization values are saved only in ignored local `.env`; the key is omitted here. No reservation was created. Test/mock/SES-disabled/maximum attempts 0 remain active. No notification dispatcher was started and no helper or n8n restart was needed.

The published node retains exactly one preflight recipient expression, preflight sender/subject/HTML, AWS credential in eu-north-1, HMAC/preflight configuration and disabled automatic retry. Delivery remains isolated from the CSV address.

All five historical SES notifications, their delivered events, recovery audits, products, and Workflow C execution records match their pre-preparation fingerprints. Each historical SES notification remains ambiguous at one attempt without a Message ID. The rejected earlier batch is unchanged.

## Next step

A fresh explicit authorization is required for exactly one live attempt for the batch/event above. Before any send, repeat safety checks, reload only the helper with the new scoped values and a one-attempt SES limit using the current diagnostic-image Compose override, and dispatch only this event. Capture provider status/code/request ID and any Message ID; restore mock mode and clear scoped values regardless of outcome. Do not reuse or reset historical notifications. Inbox receipt must be separately confirmed.

## Fresh verification results

107 notification, matching/dispatcher, offline SES contract/diagnostic, recipient-isolation, HMAC, recovery, idempotency and synthetic-fixture tests passed. Ruff, Mypy (54 source files), Compose validation with the diagnostic image override, and `git diff --check` passed. Post-test read-only checks reconfirmed historical preservation, the sole pending completion event, absent notification reservation, correct scoped authorization and healthy API/frontend/n8n endpoints. No AWS/Gemini API or live SES node was invoked.
