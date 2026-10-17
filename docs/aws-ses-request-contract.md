# Offline AWS SES request contract and rollout plan

Audit updated 2026-10-17. The rollout sections below record the original transport-patch deployment and its checks at that time. The later diagnostic-image rollout supersedes its image and override selection; use [current diagnostic rollout instructions](aws-ses-safe-diagnostics.md). The subsequent authorized SES attempt succeeded with owner-confirmed receipt; see [execution 185 evidence](aws-ses-success-evidence.md). No sending was performed during the offline audit or image rollout itself.

## Transport compatibility

**Original query-only POST: UNVERIFIED as an AWS service acceptance behavior; DOCUMENTED_UNSUPPORTED as the normative AWS Query POST format.** This distinction matters: a service may tolerate a nonconforming request, but this audit makes no such acceptance claim. **Corrected form-body POST: DOCUMENTED_SUPPORTED.**

The [AWS-authored Smithy AWS Query protocol](https://smithy.io/2.0/aws/protocols/aws-query-protocol.html#request-serialization) specifies POST to `/`, form-encoded input in the body, a form Content-Type, Content-Length, and body fields Action and Version. It specifies RFC 3986 encoding. Botocore's installed SES model independently identifies protocol `query`, API version `2010-12-01`, and operation `SendEmail`; its offline serializer produces the same decoded body parameters and Content-Type as the patched node. This establishes a supported transport contract without contacting SES. [SES common parameters](https://docs.aws.amazon.com/ses/latest/APIReference/CommonParameters.html) and the [classic API reference](https://docs.aws.amazon.com/ses/latest/APIReference/Welcome.html) confirm the required version.

The original request omitted Version, put all parameters in the URL query, and had no body or Content-Type. The prior version-only patch repaired only the first discrepancy. Its old test accepted a bodyless POST; that incomplete assertion has been replaced with the documented form transport checks. Execution 179's underlying AWS rejection remains NOT_VERIFIED because the saved output retained no provider code, message, request ID or raw request.

## Exact implementation and minimal correction

Installed code is under `n8n-nodes-base/dist/`:

- `nodes/Aws/SES/AwsSes.node.js`, type version 1: reads preflight sender/recipient/subject/HTML and constructs SendEmail parameters.
- `nodes/Aws/SES/GenericFunctions.js`: obtains credentials and invokes `requestWithAuthentication`; formerly JSON-stringified every supplied body, including a string.
- `nodes/Aws/GenericFunctions.js`: selects the configured AWS credential type.
- `credentials/Aws.credentials.js` and `credentials/common/aws/utils.js`: select the regional endpoint, construct a Smithy HTTP request, set Content-Length, and sign with service `ses` and region `eu-north-1` before HTTP transport.

`patches/n8n-2.43.5-aws-ses-version.patch` now changes exactly two files. SendEmail uses `/` and a form body with Action and Version, RFC 3986 escaping, and `application/x-www-form-urlencoded; charset=utf-8`. The SES helper passes through a string body only for that explicit form Content-Type; other request paths keep their existing serialization. This prevents a JSON-quoted form body. The patch does not change workflow expressions, credentials, preflight, HMAC, retry behavior, recovery or idempotency.

`patches/apply-n8n-ses-patch.cjs` verifies n8n 2.43.5, both original file hashes, and every patch context before writing either file during an isolated image build. Original SHA-256 values:

- SES node: `51febf78584d8a6414794ff61679e8ef3570d813fd233ade58a2134c2649a835`
- SES helper: `838a53da650c3f69e55c884f50a37c7ac558c84ce850f91b932412761b85c30e`

`infrastructure/Dockerfile.n8n-ses` derives from the exact audited base image digest `sha256:4fc4c67bf5fb990201a71d94c7070abf8dd0619cb8af1d059877a447f3640392`. There is no n8n version upgrade or migration change. No compatible official upstream replacement was established by this audit.

## Captured corrected request

The installed expression engine evaluates the checked-in workflow using synthetic data. The harness loads the actual patched node and helper, invokes the actual AWS credential signer, and replaces HTTP transport with capture. A second capture uses the files in the built derived image directly. Both run with `--network none`, a read-only filesystem and no production credentials or volumes.

```text
POST https://email.eu-north-1.amazonaws.com/
Content-Type: application/x-www-form-urlencoded; charset=utf-8
Content-Length: exact UTF-8 byte length of the serialized body
URL query: empty
Body fields:
  Action=SendEmail
  Version=2010-12-01
  Source=<synthetic controlled address>
  Destination.ToAddresses.member.1=<same synthetic controlled address>
  Message.Subject.Data=<nonempty synthetic subject>
  Message.Body.Html.Data=<nonempty synthetic HTML>
  Message.Body.Html.Charset=UTF-8
```

There is exactly one recipient, no second/empty member, CC or BCC. Synthetic text includes ampersand, plus, non-ASCII and punctuation to check encoding. The capture omits authorization headers, signatures and secret key material. The installed signer signs Content-Type, Content-Length, Host and X-Amz-Date, and hashes the exact body. An independent Node crypto HMAC implementation reconstructs the canonical request and confirms the signature; body and Content-Type tampering both invalidate it. AWS-side signature/identity acceptance remains NOT_VERIFIED.

Draft and published Workflow C retain one `toAddresses` entry, `={{ [$json.recipient] }}`, with a bound AWS credential and no automatic retry. Last inspected active version is `87b22acd-4324-40bd-94f2-6564255589a6`. The derived image changes no workflow database row or credential format.

## Recovery regression

`test_release_preserves_unrelated_event` assumed its newly inserted event was immediately due. The model assigns `next_attempt_at` using PostgreSQL time, while `claim_due()` compares against Python host time. The historical failure did not retain clock measurements. Today the original test initially passed, but a controlled one-second dispatcher-clock lag reproduced the exact `None` result. A read-only query of the disposable fixture showed the ordinary event was pending, had no recovery scope, and was not yet due. No transaction visibility or scope-filter defect was observed.

The fixture now explicitly creates a due event using the host clock minus one minute. A new deterministic boundary test proves a future ordinary event stays unclaimed, becomes claimable exactly at its due time, and a due targeted-recovery event stays excluded throughout. Production dispatcher and recovery code were not weakened or changed. Clock synchronization remains an operational requirement; the old failure's actual host/container skew cannot be reconstructed from saved evidence.

## Safe build, rollout and rollback plan from the offline audit

Build from an isolated context containing only the Dockerfile and the two patch files, never the whole worktree or `.env`. Use `docker build --network=none --pull=false` and retain the original image. The local derived tag is `loan-engine-n8n-ses:2.43.5-contract`. Before rollout, run the complete contract suite with `N8N_SES_PATCH_IMAGE` set to that tag; the harness's `installed` mode tests the built files rather than an in-memory patch. Record the resulting image ID and use that immutable ID in the rollout override.

A separately authorized operator should follow this sequence from the canonical populated SES worktree:

1. Confirm test/mock mode, SES disabled, zero attempts, no dispatcher, empty scoped SES authorizations, and no in-flight Workflow C. Record published workflow ID/version, encrypted credential bindings, execution count/latest ID, and three ambiguous notification states without exporting their contents. Prevent outbound AWS/Gemini traffic during restart verification.
2. Create a private backup directory **outside all Git worktrees**, mode 0700, and check free disk space. Stop only canonical n8n for a consistent snapshot; do not stop PostgreSQL or delete any volume. Save the current image ID and Compose project/volume mapping.
3. Dump the n8n PostgreSQL database with supported `pg_dump --format=custom`; in the canonical postgres container use its existing `POSTGRES_USER` and `N8N_DB_NAME` variables without echoing secrets. Redirect the dump to the private backup directory. Check `pg_restore --list`, checksum the artifact, and test restore in a disposable isolated database before proceeding. Preserve the existing database and role ownership.
4. Archive the stopped n8n data volume through a read-only mount in a network-disabled helper container. Privately copy ignored `.env` and any local override into the backup directory, preserving the **same encryption key**. Encrypted credentials are in PostgreSQL and require that key; a database dump alone is insufficient. Protect backups with 0600 permissions and never commit them.
5. Use a private Compose override containing only the n8n derived image ID and `EXECUTIONS_DATA_PRUNE: "false"` during verification so the historical evidence is not pruned. Keep the canonical project directory, `.env`, named volumes, database host/name/user and encryption key unchanged. The future service-only command is `docker compose --project-directory . --env-file .env -f infrastructure/docker-compose.yml -f <private-override> up -d --no-deps n8n`. Do not run `down`, delete volumes, import workflows or recreate credentials.
6. Check health, exact n8n version/image ID, credential decryptability and binding without testing the credential against AWS, region, current draft/published version, execution history, one recipient, no retry, and mock/disabled helper settings. Re-run the no-network capture against the deployed image ID. Confirm no new Workflow C execution or SES attempt occurred.
7. If any check fails, keep sending disabled and replace only the override's image with the recorded original image ID, then recreate only n8n using the same service-only command and persistent volumes. This same-version patch performs no schema migration; routine rollback should not restore over the live database. If integrity checks reveal database damage, stop and use a separately reviewed restore procedure from the validated snapshot, preserving subsequent evidence.

No backup, shutdown, restart, override activation or rollout was performed during the preceding offline-only task; the subsequent authorized local rollout is recorded below. The image build and offline capture do not authorize deployment or email sending.

## Diagnostics and remaining uncertainty

The SES helper wraps HTTP errors in NodeApiError. With continue-on-error enabled, the SES node saves only `{error: error.message}`, discarding useful provider details. A later approved diagnostic change should allowlist redacted HTTP status, AWS error code and request ID; it must not log bodies, addresses, credentials or authorization headers. This task does not change the live workflow's error handling.

Owner-confirmed IAM positive/negative simulations remain owner evidence. Sandbox/identity status, account restrictions, provider acceptance and inbox delivery were not independently tested. All three ambiguous notifications must remain untouched. A fresh batch and separate authorization are required for any future send, after controlled rollout succeeds.

## Fresh verification results

- `N8N_SES_PATCH_IMAGE=loan-engine-n8n-ses:2.43.5-contract uv run --frozen --env-file .env pytest -q tests/notifications tests/matching tests/integration tests/unit`: **129 passed**, no skipped or deselected tests. Database integration includes guarded test-database migration round trips. Notification/recovery and matching suites cover HMAC, attempt limits, idempotency, isolation and dispatcher behavior with mocked transports.
- The repaired recovery fixture separately passed under the same injected one-second clock lag that reproduced its earlier failure.
- Full project Ruff: PASS. Project mypy: PASS (52 source files); changed Python tests: PASS. All workflow JSON files parse; Compose validation and `git diff --check`: PASS.
- Changed-file secret scan: PASS across nine changed/new files, using credential patterns and private local secret/address values as non-printing comparison inputs. No environment file, backup, credential value or private address was added. This is a scoped release check, not a new full-history security audit.
- Derived image build with network-disabled build steps: PASS. Image ID `sha256:3897004d6718a62a9d9e0d1e3656911690567e1f077e85fdc2dec6ce74caa04a`; actual installed-image capture, SDK serialization comparison and independent SigV4/tamper checks: PASS.
- Live read-only postcheck: original n8n image remains healthy, active Workflow C version unchanged, latest execution still 179, three SES rows still ambiguous with one attempt and no provider ID. Both ignored configuration and running helper remain test/mock/disabled/zero-attempt; dispatcher process count is zero.

**Controlled rollout readiness: PASS for the prepared artifact and plan, contingent on the plan's backup/restore checks and separate deployment authorization. Live rollout: NOT_RUN. SES acceptance and receipt: NOT_VERIFIED.**

## Authorized local rollout

Completed 2026-10-17T09:18:20+00:00. **PASS — only the local n8n container image was replaced.** Canonical worktree: `/Users/anubhav/.superset/worktrees/Loan Engine/enthusiastic-space-05804b95`; Compose project: `loan-eligibility-engine`. n8n version remains 2.43.5.

| Artifact | Identifier |
|---|---|
| Original retained image | `sha256:4fc4c67bf5fb990201a71d94c7070abf8dd0619cb8af1d059877a447f3640392` |
| Installed patched image | `sha256:3897004d6718a62a9d9e0d1e3656911690567e1f077e85fdc2dec6ce74caa04a` |
| Patch SHA-256: repository and installed copy match | `b7927098341b069befe8c7aaa0f7ecbeeee0325f3f9aae7315ef4c91be44babd` |

### Backup verification

Preflight found healthy PostgreSQL/n8n/LocalStack, no running or waiting workflows, no pending/processing notification events, and no dispatcher. Both configuration and helper were test/mock/SES-disabled/zero-attempt. Approximately 3.3 GB was free; the n8n database was approximately 18 MB and the volume 232 KB. Both images already existed, leaving sufficient capacity.

Only n8n was stopped for consistent backups. The private directory `/Users/anubhav/.local/share/loan-engine-backups/n8n-ses-rollout-20261017` contains a custom-format PostgreSQL dump, n8n volume archive, environment/encryption-key copy, original container configuration, image IDs, checksum manifest and preservation snapshots. The directory is mode 0700 and sensitive backup files mode 0600.

The 739,071-byte database dump passed `pg_restore --list` and full `pg_restore --file=/dev/null` parsing. The 21,080-byte volume archive passed full member reading/decompression. File checksums were verified before replacement. **No database restore was executed**, consistent with the restriction against database modification. Backups are outside Git and were not uploaded.

### Rollout and preservation

The service-only Compose replacement used an immutable image override, explicit canonical project directory/project name, and `--no-deps --pull never`. Existing environment values, encryption key, ports, webhook URLs, database and volume mappings were preserved. The guarded rollback path was available but was not needed.

- n8n health and editor HTTP responses: PASS. PostgreSQL and LocalStack remain healthy.
- Full before/after hashes and counts match for encrypted credentials, workflow definitions/history and execution entities/data. The initial owner-row hash also matched; a later check detected only `user.updatedAt` changing during runtime. Direct field comparison with the backup confirmed all other owner fields, including password, identity and access settings, are identical. This timestamp-only difference is recorded and does not require rollback. Interactive owner login was not performed.
- Published workflows remain active at exactly these versions: A `a8d31f49-60bb-4ddc-8db5-548ed12a9c75`; B `5b92a0f6-db8f-4caf-8d05-92aaaf1f2fc5`; C `87b22acd-4324-40bd-94f2-6564255589a6`.
- All 40 execution records are preserved; latest ID remains 179. No unexpected workflow execution was observed.
- AWS credential binding/decryptability: PASS; region remains `eu-north-1`. Only metadata booleans and region were emitted. One preflight recipient, no additional recipients, no retry, HMAC and preflight nodes are preserved.
- Installed SES node/helper hashes match the tested immutable image. A network-disabled synthetic capture against that image passes form transport, Version, single-recipient, body/header signing and tamper checks. Fresh pre- and post-rollout contract suites each passed **40 tests**.
- Application notification/outbox/workflow-execution table fingerprints match exactly. Three historical SES rows remain ambiguous, one attempt each, no Message ID. Test/mock/disabled/zero-attempt state and stopped dispatcher remain intact.

No AWS API command, credential connection test, SES node or workflow was invoked. Unchanged execution and application records support absence of a new SES attempt; a separate network packet audit was not performed. Provider acceptance and inbox receipt remain NOT_VERIFIED.

### Persistent image selection and rollback

Image selection is a **private Compose override**, not a tracked Compose edit. Future n8n recreation must retain it; the base Compose file alone selects the original image. From the canonical worktree use the existing Compose command with explicit `-p loan-eligibility-engine --project-directory . --env-file .env`, the base `-f infrastructure/docker-compose.yml`, and a second `-f /Users/anubhav/.local/share/loan-engine-backups/n8n-ses-rollout-20261017/image-override.yml`, followed by `up -d --no-deps --pull never n8n`.

For a separately requested rollback, substitute `rollback-override.yml`; it selects the retained original image while preserving volumes/configuration. Recheck health and preservation snapshots. Routine image rollback needs no database restore. Do not overwrite newer database state without a separate integrity review. **Rollout PASS; rollback readiness PASS; rollback execution NOT_RUN. No sending is authorized.**
