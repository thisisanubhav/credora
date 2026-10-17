# Controlled AWS SES delivery evidence

## Outcome: PASS — accepted and owner-confirmed receipt

On 2026-10-17 the owner authorized exactly one send from the prepared lowercase-identity batch. Fresh preflight passed before temporary SES activation. No further send or retry was made.

| Check | Evidence |
|---|---|
| Region | `eu-north-1` |
| Batch | `5bac37d6-f3b2-435a-9341-48f465ae47ba` |
| Matching execution | Workflow B **184**, success; one synthetic potential match |
| Exact dispatched completion event | `8412f11b-8c63-55d7-9679-c39fc8efa128` |
| Workflow C | **185**, terminal success; one SES node run |
| Published workflow version | `87b22acd-4324-40bd-94f2-6564255589a6` |
| Execution timestamps | 2026-10-17 10:26:22.039–10:26:23.256 UTC (1.217 seconds) |
| Provider output | `SendEmailResponse` with Message ID; no node error |
| SES Message ID | `011001a14965fca7-6ffddebd-044e-4816-adf1-dc853e3eb9f7-000000` |
| Notification | `dc522a29-2207-4507-b7bc-3fe4fd11ecac`: `sent`, attempt_count **1**, matching persisted Message ID, no error code |
| Completion event | `delivered`, retry_count **1**; zero pending/processing completion events |
| Inbox evidence | Owner explicitly answered “Received with label and disclaimer” after checking the controlled Gmail inbox |

The owner confirmed the synthetic label and “These are potential matches, not guaranteed loan approvals.” Receipt is owner-attested, not independently inspected by the agent. A screenshot/video remains to be captured for submission.

## Safety and preservation

- One exact-event dispatch, one new Workflow C execution, one SES node invocation, one recorded attempt. No automatic retry or unscoped dispatcher.
- Only the existing controlled recipient was used; no CSV recipient was used.
- After terminal execution, guarded cleanup restored test/mock mode, SES disabled, maximum attempts zero, and cleared both scoped authorization fields. Healthy running helper settings matched ignored local configuration.
- Five prior ambiguous notifications remain unchanged at one attempt and without Message IDs. Their full-row fingerprints, historical events and recovery audit fingerprints were unchanged.
- Published workflow fingerprints unchanged; patched n8n image remains `sha256:7a6c3576b77f302b0ba1c13bb9de2ea2687487a52c5466a99dd6d248ff4586e2`.
- No IAM changes, infrastructure deployment, additional AWS operation, or Gemini call was performed.

## Interpretation and remaining work

The successful attempt followed the owner's creation/verification of the exact lowercase SES identity and prior offline request repairs. It demonstrates that the current request and authorization are accepted. It does not retroactively prove the sole cause of every earlier rejection; their detailed provider messages were not retained.

Preserve historical attempts. Capture received-email evidence with private details redacted for the demonstration video. Live Gemini use, evaluator access, video and submission remain incomplete. No further SES send is authorized by this completed one-attempt request.

## Fresh regression checks

- Notification, recovery, matching and synthetic-preparation suite: **106 passed, 1 skipped** in 15.99 seconds.
- Separate SES contract and installed diagnostic-image suite: **22 passed** in 2.17 seconds, no skips. All tests used offline/mocked transport; no additional live send.
- Ruff: PASS. Mypy: PASS, 54 source files.
- Workflow JSON parsing, Compose configuration validation, Git diff whitespace and changed-document secret/address scans: PASS.
