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

## Authorized local rollout attempt — 2026-10-17

**ROLLED BACK / preservation gate failed.** The diagnostic image is built and tested, but is not the image currently running.

- Derived image: `sha256:7a6c3576b77f302b0ba1c13bb9de2ea2687487a52c5466a99dd6d248ff4586e2`.
- Restored, healthy runtime image: `sha256:3897004d6718a62a9d9e0d1e3656911690567e1f077e85fdc2dec6ce74caa04a`.
- Reproducible recipe: `infrastructure/Dockerfile.n8n-ses-diagnostics`. Build from a minimal temporary context containing that Dockerfile and its four listed patch files, not the whole worktree. The repository's default Docker ignore rules deliberately exclude patches.
- Network-disabled build succeeded from the pinned local base. Installed diagnostic-image checks passed **43 tests**, including request contract, signatures and all three error diagnostic cases. The diagnostic harness now supports `N8N_SES_DIAGNOSTICS_IMAGE` to test built files rather than only an in-memory transform.
- Verified fresh backups are outside Git at `/Users/anubhav/.local/share/loan-engine-backups/n8n-ses-diagnostics-rollout-20261017`. PostgreSQL custom archive passed full decode to `/dev/null` without a database restore. Volume archive was fully read; encryption configuration and original image metadata were preserved with restricted permissions. Checksums were validated before rollout.
- Disk checks showed approximately 3 GiB available on host and Docker filesystem; database size was approximately 18 MB. Docker's aggregate disk-usage command reported a missing snapshot, but actual image inspection, isolated image tests and build succeeded. No prune or volume deletion was performed.
- Only n8n was recreated, preserving its volumes, encryption key and environment. The post-start preservation comparison detected `workflow_history` falling from 10 rows to 7. The guard restored the previous image automatically. No database restore was performed.
- Removed old Workflow C version IDs: `fbff61e0-10eb-4c43-b980-5d8d6c34466a`, `0eb07b36-8cab-44a7-a115-720178c52b54`, `36d179c0-d3cf-4fd4-89c6-a59a7e87dbe7`. Their backup creation timestamps are 2026-10-16 around 09:19–09:26 UTC. All seven remaining rows are byte-equivalent to their backup values.
- Installed `WorkflowHistoryManager.prune()` deletes older versions except current/active ones, using the configured/license-bounded retention window. Automatic retention is a likely explanation for the old-row removal; the precise triggering invocation was not captured. Do not claim this diagnostic code deleted the rows or that full history preservation passed.
- Final verification against the pre-rollout snapshot found **only workflow_history differs**. Published workflows, encrypted credentials, owner records, all execution records and application notification/outbox/recovery records are unchanged. Current Workflow C remains `87b22acd-4324-40bd-94f2-6564255589a6`; latest execution is 181. Four historical SES notifications remain ambiguous with one attempt and no Message ID.
- Mock/disabled/zero-attempt settings remain active. No pending completion events or dispatcher. No workflow was manually invoked, no SES send was performed, and no AWS API was called by this rollout.

### Remaining gate

Before another rollout, determine an appropriate history-retention/preservation approach. The three removed history rows remain in the verified backup. Do not blindly restore the whole n8n database over current state or modify history records without a reviewed recovery plan. The current saved original image override remains the safe runtime choice; do not use the diagnostic candidate override as a startup default yet. Further email attempts remain unauthorized.
