# Eight-minute demonstration script (recording not yet made)

**Truthful scope:** local PostgreSQL, LocalStack and self-hosted n8n; synthetic positive matches; mock-only notifications. Do not show a mock row as an inbox receipt or call LocalStack AWS. The PDF additionally requires a received SES email, which is **unfulfilled** under the ₹0/no-real-email rule. Target 7:45–8:15; record a 5–10 minute video only after rehearsing. Blur personal account information and never display `.env` or n8n credentials.

| Time | Screen and narration | Expected evidence |
|---|---|---|
| 0:00–0:45 | README overview and assignment problem. State local-only scope and potential-not-approval policy. | [Requirements matrix](assignment-compliance-final.md) |
| 0:45–1:45 | [Final architecture](final-architecture.md): presigned S3 upload, ingestion, PostgreSQL outbox, n8n A/B/C, mock/SES distinction. Explain why Python, SQL first and outbox. | Diagram and [offline AWS design](aws-deployment-design.md) |
| 1:45–2:45 | n8n Workflow A: Schedule Trigger, allowed sources, signed fetch/extract/validate/persist, summary. Show two official URLs and current `review_required`; a recrawl remains version 1. | Fresh-clone n8n A execution 36 and recrawl, [source registry](loan-sources.md) |
| 2:45–4:15 | Browser at `127.0.0.1:3107`: upload the explicitly synthetic three-row CSV via the demo checkbox. Show direct multipart request to LocalStack, progress and real batch status. Explain invalid-row pagination without displaying applicant values. | [M10 screenshots](../artifacts/m10/real-initial-desktop.png), [upload](../artifacts/m10/real-upload-state.png), [completion](../artifacts/m10/real-ingestion-complete.png) |
| 4:15–5:45 | n8n Workflow B: signed webhook, batch claim, SQL candidate page, deterministic rule branch, optional advisory Gemini, match persistence, completion outbox. Query counts, not PII. State bank products are excluded. | Fresh batch `823c5275-6d36-44fa-9a6f-0cf2ec229dfa`, 3 synthetic matches; n8n B 34 terminal success |
| 5:45–6:45 | n8n Workflow C: signed completion event, group one-per-user, recipient guard, HTML template, mock branch versus real SES node, record result. Explain ambiguous SES acceptance. | 2 `mocked` groups, 1 unmatched user; n8n C 35 terminal success, zero real sends |
| 6:45–7:30 | [Performance report](performance-report.md): 500,000 theoretical pairs → 100,499 SQL candidates; 79.9% reduction; 0 LLM calls. State benchmark exclusions and commands. | Single local 10k/50 run, not a cloud throughput claim |
| 7:30–8:00 | Security and limits: loopback editor, HMAC/replay, synthetic isolation, no OIDC cloud UI, no RDS/SES/Gemini live evidence. End with repo/documentation location, not a claim of full assignment completion. | [Security audit](security-audit.md), [submission summary](submission-summary.md) |

## Commands and safe query cues

### Exact n8n node cues

- **A:** `Daily Schedule` (24 hours) or `Manual Trigger`; `Start Discovery Run`; `Source Configuration`; for each source, `Fetch Official Source` → `Extract Deterministic Criteria` → `Needs Gemini?` (skips without authorized key) → optional `Gemini Qualitative Extraction` → `Validate Source Evidence` → `Persist Product Version` → `Record Source Outcome`; finish at `Execution Summary`. Each private HTTP step has a `Sign ...` Code node immediately before it. Explain that these sign route/body/timestamp/nonce, not financial decisions.
- **B:** `Signed Matching Webhook` → `Authenticate and Claim Event` → `New or Resumable Event?` → durable/duplicate acknowledgement. New work passes `Load Batch Metadata` → `SQL Candidate Prefilter` → `Deterministic Rule Evaluation` → `Selective Gemini Advisory` (zero calls for current demo) → `Persist Potential Matches` → `More Candidate Pages?` loop → `Commit Completion Event` → `Execution Summary`. The `Sign ...` nodes authenticate every private helper operation; duplicates take `Acknowledge Duplicate` and do not rematch.
- **C:** `Signed Notification Webhook` → `Authenticate and Durably Accept Event` → new/duplicate acknowledgement → `Fetch and Reserve Next User Group` / `All User Groups Complete?` loop → `Already Handled or No New Matches?` → `Group Verified Matches and Compose Text + HTML` → `Enforce Test Recipient and Begin Attempt` → `Local Mock or Explicit SES?`. The exercised path is `Local Mock Acceptance (No Email)` → `Record Mock Result` → `Notification Execution Summary`. Point to `AWS SES Send to Controlled Test Inbox` and `Record SES Acceptance or Ambiguity` as **unexecuted** under this budget. `Sign ...` nodes authenticate the private helper steps, including mock/result recording.

From the repository root after `make init`, `uv sync --frozen`, `npm ci --prefix apps/web`, `make up db-upgrade db-role s3-init`, import/publish A/B/C, and seed only synthetic fixtures:

```sh
make api                         # terminal 1
make local-worker                # terminal 2
uv run --frozen --env-file .env python -m services.eligibility.dispatcher --watch # terminal 3
NEXT_PUBLIC_ENABLE_DEMO_UPLOAD=1 make web-dev   # terminal 4
make notification-e2e            # headless fallback; still exercises actual n8n B/C
make matching-benchmark          # guarded synthetic benchmark, when time permits
```

Use `make db-status` and `make status` for health. In the n8n editor, inspect execution IDs and node names without exposing payloads, signer headers, test emails or credentials. Safe database queries for an observed batch UUID (replace `:batch_id` with a bind parameter, never paste applicant data): `SELECT status, accepted_rows, rejected_rows FROM upload_batches WHERE id = :batch_id;`, `SELECT count(*) FROM matches m JOIN users u ON u.id=m.user_id WHERE u.upload_batch_id=:batch_id;`, and `SELECT n.status, count(*) FROM notification_logs n JOIN users u ON u.id=n.user_id WHERE u.upload_batch_id=:batch_id GROUP BY n.status;`.

## Recovery during recording

- If Docker/OrbStack restarts, wait for `make up`, then rerun `make s3-init` to restore bucket/CORS before browser upload.
- If a workflow import deactivates a webhook, publish A/B/C and restart n8n before testing. Do not fake a trigger by directly calling the helper.
- If an outbox event is pending, inspect dispatcher/n8n health; the watch loop retries. Replaying the same signed event must not duplicate matches or reservations.
- If a live source is unavailable or robots denies it, show the failure outcome and previously saved version without claiming a fresh crawl.
- If browser timing misses the progress bar, show the already-captured local progress screenshot and explain that the transfer may complete rapidly; do not infer failure from a missing transient UI state alone.
- If an SES credential is absent, stop at the mock branch. There is no received-email screenshot to substitute.
