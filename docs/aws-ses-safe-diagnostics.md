# SES safe diagnostics — offline preparation

Status: prepared for review; **NOT DEPLOYED**. No SES attempt is authorized by this work.

## Why this is needed

Execution 181 saved only `Bad request - please check your parameters`. The installed SES node catches errors and emits only `error.message`. n8n's NodeApiError maps different HTTP 400 responses to that same text. Offline injection reproduced this for both MessageRejected and InvalidParameterValue. The exact provider reason for execution 181 remains unknown.

Read-only examination of execution 181 found nonempty trimmed sender, recipient, subject and HTML strings; sender equals recipient, with valid single-address syntax. The disclaimer is present. A separate network-disabled check through the installed legacy HTTP adapter and Axios transformation preserved the signed body, URL, Content-Type, content length and authorization. No new request-construction defect was established.

## Proposed overlay

`patches/apply-n8n-ses-diagnostics.cjs` first applies the existing transport patch in memory, using its original-file SHA-256 gates and exact n8n 2.43.5 version check. It then replaces the single continue-on-error output location with a fixed generic error and a `ses_diagnostics` object. Imports do not modify files. Only explicit build-time `--apply` writes validated outputs.

The standalone sanitizer in `patches/ses-safe-diagnostics.cjs` retains only:

- `http_status`: numeric 400–599, otherwise null.
- `aws_error_code`: one of the explicitly enumerated provider error codes, otherwise null.
- `request_id`: UUID-shaped provider request ID, otherwise null.

Traversal is restricted to known response/cause fields and bounded to 32 entries. XML extraction is limited to 64 KiB, extracts only Code/RequestId, and does not expand entities. Unknown codes and non-UUID request IDs are deliberately dropped. Null means unavailable or rejected by this filter, not provider success.

No raw message, description, XML body, address, signature, credential, request options, or authorization header is copied into node output. The existing error key remains truthy, so Workflow C still records an uncertain result conservatively. Request construction, credential selection, recipient preflight, HMAC, idempotency, and attempt limits are unchanged. No retry is added.

This narrows this node's handled-error output only. It is not a claim that all upstream n8n logging or saved preflight data is free of sensitive information. An unexpected unhandled failure remains subject to n8n's existing behavior.

## Offline verification

The new harness compiles the transformed pinned SES node and helper in a separate read-only Docker container with networking disabled. Synthetic errors pass through the real NodeApiError wrapper and SES catch block. Tests distinguish MessageRejected, InvalidParameterValue, and SignatureDoesNotMatch while retaining status and synthetic request ID. They reject unknown identifiers, malformed fields, oversized XML, and cyclic causes, and check structured/header response metadata. A sensitive sentinel in error messages and request options never appears in the captured node output. Existing signing checks still pass.

The existing production Dockerfile, deployed image, published workflow, credentials, database records, and ignored notification configuration are not changed by this preparation.

## Future rollout, not executed

1. Review this overlay and test results; obtain separate local-rollout authorization.
2. Back up n8n PostgreSQL and its data volume/encryption configuration outside Git. Record the current immutable image and workflow/execution baselines.
3. Build a separate derived image from the previously verified pristine n8n 2.43.5 base, copying all four patch support files and using `node apply-n8n-ses-diagnostics.cjs --apply` instead of the transport-only installer. Do not apply twice or patch the running container.
4. Verify the resulting image offline, including transport and diagnostic output; retain the current image for rollback.
5. Replace only n8n through the canonical saved Compose override after approval. Preserve all volumes and credentials. Verify workflows, execution history, recipient expression and mock/disabled safety settings.
6. Roll back by selecting the prior immutable image with the same volumes if verification fails. Do not blindly restore database backups over newer state.

A future email attempt requires separate explicit authorization and fresh isolated preparation. Do not replay execution 181 or any ambiguous notification. This diagnostic patch improves evidence for a future failure; it is not a fix for the still-unknown AWS rejection.

### Recorded results

Fresh notification suite: **88 passed**. After adding an explicit one-request assertion, all three diagnostic cases passed again. Ruff passed; Mypy passed for 54 source files; `git diff --check` passed. Final read-only safety checks confirm mock transport, SES disabled, authorization cleared, no dispatcher, four ambiguous one-attempt/no-Message-ID notifications, no pending completion event, and latest Workflow C execution unchanged at 181.
