# Submission and fresh-checkout checklist

The PDF permits local deployment and says cloud spend is not expected. This submission honors the stricter ₹0/no-real-email instruction: the AWS template is offline-only and the SES receipt requirement remains unmet. **Do not submit the form automatically.**

## Clean checkout rehearsal, executed 2026-10-15

An isolated `git clone --no-hardlinks` of the M10 committed branch was created at a temporary path with **no copied `.env`, `.venv`, `node_modules`, or Docker volumes**. New `make init` keys and a separate Compose project (`COMPOSE_PROJECT_NAME=loan-engine-m10-fresh`) were used. The old project was stopped without deleting its volumes. On a machine where another checkout is running, use a unique Compose project and free host ports; the environment checker currently expects the documented loopback URLs.

```sh
make init
uv sync --frozen
npm ci --prefix apps/web --no-audit --no-fund
make up
make db-upgrade db-role s3-init smoke
make discovery-import matching-import notification-import
# Publish each imported workflow and restart n8n, as shown in README Quick start.
make notification-e2e
make web-test web-e2e web-lint web-typecheck web-build
```

Actual results: Python install **PASS**; first Docker build **FAIL** when host disk fell to ~116 MiB and OrbStack disconnected; after reclaiming ignored build/dependency caches and restarting OrbStack, isolated Compose/health **PASS**; all nine migrations and runtime role **PASS**; three workflow imports/publishes **PASS**; local B/C E2E **PASS** (n8n IDs 1/2); full frontend install initially **FAIL** on `ENOSPC`, then **PASS** after clearing regenerable npm cache; 4 frontend unit, 8 mocked browser tests, lint, types and production build **PASS**. The first real browser test **FAIL** because a daemon restart lost LocalStack bucket/CORS; `make s3-init` restored it and replay **PASS**. These are setup/host-capacity recovery facts, not hidden successful first attempts. Reserve at least 2 GiB free disk beyond images/caches before a reviewer setup.

The clean clone's real browser batch `823c5275-6d36-44fa-9a6f-0cf2ec229dfa` accepted 3 users, committed/delivered both outbox events, produced 3 synthetic matches and 2 `mocked` notification rows; n8n B/C executions **34/35** ended `success`. Screenshot evidence: [desktop](../artifacts/m10/real-initial-desktop.png), [mobile](../artifacts/m10/real-initial-mobile.png), [transfer](../artifacts/m10/real-upload-state.png), [ingestion](../artifacts/m10/real-ingestion-complete.png). Workflow A n8n **36** finished with SBI and Axis created as version 1 and `review_required`; immediate recrawl returned `unchanged` for both, leaving one version each. No Gemini, SES or AWS request was made. Screenshots were reviewed for applicant addresses and secrets.

## Repository release gate

- [ ] Verify `gh repo view thisisanubhav/loan-eligibility-engine --json isPrivate,viewerPermission,defaultBranchRef` reports private and authorized.
- [ ] Verify `git remote -v`, ancestry, clean working tree, and all expected tracked deliverables.
- [ ] Scan **all Git-history blobs** for keys/tokens/private-key blocks and inspect credential-like assignments. Stop publication on a real credential; rotate and remediate before any push.
- [ ] Confirm ignored `.env`, `apps/web/.env.local`, `node_modules`, `.venv`, `.next`, `.build` and local test outputs are not staged.
- [ ] Review screenshot/fixture content for PII; do not commit supplied CSV data.
- [ ] Run tests and offline package checks; do not deploy Serverless.
- [ ] Push the verified M10 branch to the existing private repository, never with `--force`. Verify remote README, code, migrations, Compose, Serverless, workflows, tests and docs at the pushed SHA.
- [ ] Invite the four PDF accounts with **read-only** repository access. Record pending versus accepted precisely.

## Human completion gate

- [ ] Record a truthful 5–10 minute video using [the script](final-demo-script.md) and [recording checklist](final-demo-checklist.md); paste a real link below only after it exists.
- [ ] The PDF asks for a received AWS SES email in the video. Under the current prohibition this is **BLOCKED_BY_ZERO_BUDGET / no-real-email authorization**. Mock records are not an alternative receipt. Owner must decide whether to seek explicit future authorization or submit with a disclosed gap.
- [ ] Confirm evaluator invitations were accepted (pending invitations do not prove access).
- [ ] Owner checks the 72-hour deadline against the original assignment email; receipt time is unknown here.
- [ ] Owner submits repository and actual video links at [the assignment form](https://docs.google.com/forms/d/e/1FAIpQLSe1ET4U8rOcPM3VGJ8fT5HhigTO9fKuDlsB_wHtB5acWys9XQ/viewform). No form submission is performed by this project.

Repository: <https://github.com/thisisanubhav/loan-eligibility-engine> (private). Video link: **NOT YET AVAILABLE**. Final pushed commit SHA and invitations are recorded in the M10 handoff, not claimed by this pre-publication checklist.
