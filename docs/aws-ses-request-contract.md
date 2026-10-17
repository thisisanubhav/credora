# Offline AWS SES request-contract audit — 2026-10-17

## Scope and evidence

This audit used the populated SES worktree, the checked-in Workflow C export, read-only inspection of draft and published n8n workflow rows, and the installed `n8nio/n8n:2.43.5` image. No production workflow, notification, dispatcher, IAM setting, or running n8n installation was changed. The request harness runs a separate container with `--network none`, a read-only filesystem and repository mount, synthetic AWS credentials and `.test` addresses, and a mocked transport. It calls the installed SES node and AWS credential signer, then captures only sanitized request fields before any HTTP I/O.

The installed SES node is `n8n-nodes-base/dist/nodes/Aws/SES/AwsSes.node.js` (type version 1, audited file SHA-256 `51febf78584d8a6414794ff61679e8ef3570d813fd233ade58a2134c2649a835`). The call path is `AwsSes.execute` → `Aws/SES/GenericFunctions.awsApiRequestSOAP` → `Aws/GenericFunctions.getAwsCredentials` → `this.helpers.requestWithAuthentication` → `credentials/Aws.credentials.js` → `credentials/common/aws/utils.js` (`awsGetSignInOptionsAndUpdateRequest`, `signOptions`, AWS Signature Version 4) → mocked HTTP transport. The actual network transport is never called in this audit. The helper selects `email.eu-north-1.amazonaws.com`, signs for service `ses` in `eu-north-1`, and passes the signed URL to transport.

## Captured final request

The original installed node produced this structure, using only synthetic values:

| Field | Captured result | Assessment |
|---|---|---|
| Method / host / path | `POST https://email.eu-north-1.amazonaws.com/` | VALID endpoint and region |
| Query `Action` | `SendEmail` | VALID |
| Query `Version` | **absent** | **CONFIRMED_DEFECT** against the classic SES common parameters |
| Query `Source` | one synthetic sender string, percent encoded | VALID shape; AWS identity acceptance NOT_VERIFIED |
| Query `Destination.ToAddresses.member.1` | one synthetic controlled recipient string, percent encoded | VALID shape; no `.2`, CC, BCC or empty member |
| Query `Message.Subject.Data` | one nonempty synthetic string | VALID shape |
| Query `Message.Body.Html.Data` / `.Charset` | one nonempty synthetic HTML string / `UTF-8` | VALID shape |
| Body / `Content-Type` | absent / absent; all action parameters in URL query | **POSSIBLE_DEFECT**: query-only POST acceptance by SES was not established offline |
| Authentication | SigV4 `Authorization` header, redacted; captured scope ends `/eu-north-1/ses/aws4_request` | VALID local signing shape; AWS signature acceptance NOT_VERIFIED |

The installed node uses `encodeURIComponent` on the preflight fields; the capture confirmed percent-encoded special characters. Its `setParameter` numbers destinations from 1. The checked-in workflow and both current n8n draft and published version `87b22acd-4324-40bd-94f2-6564255589a6` have exactly one `toAddresses` entry, `={{ [$json.recipient] }}`, and no additional recipient fields. The installed expression engine evaluated this to one string. The node's `encodeURIComponent` coerces the resulting single-element array to that one string. A nested array is not serialized into an additional recipient in this specific configuration.

[SES classic common parameters](https://docs.aws.amazon.com/ses/latest/APIReference/CommonParameters.html) mark `Action` and `Version` as required. [The classic SES API reference](https://docs.aws.amazon.com/ses/latest/APIReference/Welcome.html) identifies the version as `2010-12-01`; [SendEmail](https://docs.aws.amazon.com/ses/latest/APIReference/API_SendEmail.html) defines the source, destination and message fields. The published workflow's saved execution 179 contains only n8n's generic “Bad request - please check your parameters” error, with no provider error code, message, request ID or raw request. Therefore **missing `Version` is a confirmed local contract defect, but its responsibility for execution 179 remains unproven**. Query-only POST with no `Content-Type` differs from documented form-body POST examples for other AWS Query services; this audit did not find SES-specific proof that it is rejected, so it remains a possible defect rather than a confirmed one.

## Minimal repair prepared offline

The SES node has no supported `Version` configuration option. No compatible official fix was verified, and the live n8n instance was not upgraded. A one-line, version-pinned patch is prepared at `patches/n8n-2.43.5-aws-ses-version.patch`. It adds `Version=2010-12-01` only to the `SendEmail` query. The offline harness checks the installed file hash, applies the patch **in memory**, invokes the real node and signer, and captures the final request. The patched capture has exactly one controlled recipient and the required `Action` and `Version`; sender, subject, HTML, HMAC preflight, credential binding and notification idempotency are unchanged. This patch does not address the query-only POST uncertainty.

This is **not deployed**. A separate authorized rollout would require a backed-up, version-pinned custom image or upstream n8n fix, verification of the image file hash, workflow/credential/PostgreSQL compatibility, isolated smoke tests, planned n8n restart, published-version verification, and another offline capture of the deployed image before any separately authorized live send. Do not mutate the running container in place, upgrade n8n automatically, replay ambiguous notifications, or use this document as send authorization.

## Negative and regression evidence

`tests/notifications/ses_offline_capture.cjs` captures the installed final request in a network-disabled container. `tests/notifications/test_ses_http_contract.py` asserts that the unpatched request lacks `Version` and the patched request has it. Its local gate rejects empty, multiple and extra-empty recipients; missing sender, subject and HTML; malformed sender; wrong region; missing version; malformed query encoding; unsupported parameters; and a recipient that differs from the controlled sender. It also fails if the checked-in export gains a recipient entry or CC/BCC fields. These tests do not make AWS calls or claim the installed node itself rejects every malformed value.

The prior `tests/notifications/test_ses_contract.py` covers the current export and published parameter shape, installed n8n expression evaluation, Botocore's local shape validation, synthetic content and CSV-address isolation. Botocore type validation does not establish AWS account, identity or sandbox acceptance. Current fresh test results and any pre-existing test failure are recorded in the final audit report.

Fresh local results: SES contract tests **34 passed** with `.env` supplying only local test and n8n database configuration. The notification suite ran **77 passed, 1 failed**; `test_release_preserves_unrelated_event` repeatedly found `claim_due()` returned `None` for the synthetic test event, including when run alone. This is a separate recovery/dispatcher test failure and does not exercise SES request construction. The same suite with that one test deselected passed **77/77**. Ruff and mypy passed for both SES test files; workflow JSON parsing and `git diff --check` passed. A changed-file secret scan found no access-key pattern, private key, non-test email or apparent secret assignment. No full repository security scan or live provider validation was performed.

## Error diagnostics and remaining uncertainty

`Aws/SES/GenericFunctions.awsApiRequest` wraps transport errors with `NodeApiError(..., {parseXml:true})`. `NodeApiError` maps HTTP 400 to the generic text seen in execution 179. With Workflow C's continue-on-error behavior, the SES node emits only `{error: error.message}`; it discards provider code, message, request ID, status and response metadata from the saved output. A future approved diagnostic change should retain only an allowlisted, redacted provider error code, HTTP status and request ID in application evidence; it must not log authorization headers, signatures, addresses, full bodies or credentials. No diagnostic change was made to the live workflow here.

**Readiness:** offline patch validation PASS; live SES request acceptance, Message ID and inbox receipt NOT_VERIFIED. Another live attempt requires separate authorization, a fresh batch, reviewed rollout and the existing one-attempt safety gate. The three historical ambiguous notifications remain excluded from any retry.
