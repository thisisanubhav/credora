# Demonstration checklist

## Before recording

- [ ] Confirm the private repo and current commit; do not display tokens or `.env`.
- [ ] Confirm ₹0 scope: no AWS deployment, SES send, paid Gemini request or public host.
- [ ] `make up db-status smoke s3-init` succeeds and n8n A/B/C are imported **and published**.
- [ ] Start FastAPI, local S3 event bridge, dispatcher, and Next.js with the local synthetic flag. Keep `NOTIFICATION_TRANSPORT=mock` and `NOTIFICATION_SES_ENABLED=0` in ignored `.env`; do not show their secret-bearing file on screen.
- [ ] Check the browser at `127.0.0.1:3107` and n8n at `localhost:5678` before capture.
- [ ] Seed labelled synthetic fixtures only; verify official SBI/Axis records are `review_required`.
- [ ] Choose a CSV containing only `example.com` test addresses. The six required headers are in [CSV contract](csv-contract.md). Do not use the supplied sample addresses for delivery.
- [ ] Practice 8-minute timing and prepare safe count-only SQL queries.

## During recording

- [ ] Explain every logical node of Workflow A, B and C, including failure/retry branches.
- [ ] Show a real local browser presign/LocalStack upload and backend status; do not call this AWS S3.
- [ ] Show n8n terminal execution states, outbox delivery, three synthetic matches and two mock notification groups.
- [ ] Say “potential matches, not guaranteed loan approvals” and show synthetic labelling.
- [ ] State clearly that the AWS SES node is configured but **not invoked**; no email has been sent or received.
- [ ] Show measured benchmark scope and exclusions rather than estimating cloud throughput.

## After recording

- [ ] Check duration is 5–10 minutes, sound/screens are readable, and no PII, secrets, signer payloads or Gmail address are visible.
- [ ] Host a private/unlisted video at an owner-approved destination, then replace the placeholder in [submission checklist](submission-checklist.md).
- [ ] Review exact evaluator invitations and pending/accepted status; do not claim a pending invitation was accepted.
- [ ] Owner decides how to explain the missing SES inbox receipt before submitting. Do not fabricate it.
- [ ] Owner alone submits the repo and actual video links through the form; this checklist does not submit anything.
