# Incremental Development Roadmap

## Delivery principles

- Each milestone is independently reviewable and leaves the main branch runnable.
- Mandatory assignment scope precedes optional polish.
- Local tests/fakes are the default. No AWS deployment or paid Gemini call is required for milestones to pass.
- n8n owns workflow decisions; Lambda handlers remain transport/ingestion plumbing.
- Schema and workflow contracts are versioned before consumers are built.
- Every retryable boundary is tested for duplicate delivery.

The files below are planned paths, not evidence that they already exist.

## M1 - Repository and local infrastructure

**Objective:** Make a new checkout consistently installable, lintable, and able to start the local dependencies without implementing business behavior.

**Implementation scope**

- Establish Python 3.12 and Node version/tooling conventions.
- Add Docker Compose for PostgreSQL and pinned self-hosted n8n with healthchecks, named volumes, an isolated network, and no embedded secrets.
- Add task commands for install, lint, typecheck, test, compose up/down, and n8n workflow import/export validation.
- Add structured configuration loading and logging skeletons only.
- Add CI for formatting, lint, typecheck, and empty/smoke test suites.

**Files to create/modify**

- `pyproject.toml`, lockfile, `package.json`/workspace configuration
- `.python-version`, `.nvmrc` or equivalent pinned Node declaration
- `infrastructure/docker-compose.yml`
- skeleton package manifests under `apps/` and `services/`
- `Makefile` or a small cross-platform task runner
- `.github/workflows/ci.yml`
- `.env.example`, `.gitignore`, `README.md`

**Acceptance criteria**

- A documented command starts healthy PostgreSQL and n8n locally.
- n8n editor is reachable locally; its database persists across container restart.
- Python/TypeScript imports and configuration smoke tests pass with placeholder values.
- No AWS/Gemini/SES call or real credential is required.

**Required tests:** Compose config validation, container health smoke test, configuration failure/success tests, lint/typecheck/test CI smoke.

**Dependencies:** Docker, Python 3.12+, supported Node LTS, chosen package managers.

**Definition of done:** A clean checkout follows README setup successfully; CI is green; images/dependencies are pinned; secret scan finds no credential. This planning task stops before this milestone’s implementation.

## M2 - Database models and migrations

**Objective:** Implement the reviewed relational contract and prove constraints/idempotency locally.

**Implementation scope**

- SQLAlchemy models and Alembic baseline migration for all approved tables.
- Pydantic contracts for upload/user/product rules/event envelopes.
- Database roles/grants for local parity where practical.
- Test factories only; no real scraped product criteria.

**Files to create/modify**

- `database/alembic.ini`, `database/migrations/`, initial revision
- `services/common/db.py`, `services/common/models/`, `services/common/schemas/`
- `database/seeds/README.md`
- database unit/integration tests

**Acceptance criteria**

- Upgrade from empty DB and downgrade/re-upgrade work locally.
- FK, check, partial unique, and idempotency constraints match `database-design.md`.
- Eligibility JSON schema rejects unknown operators, missing evidence, and invalid ranges.

**Required tests:** Migration round trip, model/schema validation, duplicate batch/user/product-current/match/event/notification cases, transaction rollback.

**Dependencies:** M1; decisions on partial-row policy, currency, `CITEXT`, UUID strategy, employment vocabulary.

**Definition of done:** Schema review approved; tests run against real PostgreSQL (not SQLite); no business workflow or cloud resource is deployed.

## M3 - CSV ingestion pipeline

**Objective:** Upload directly to object storage, process a batch idempotently, and commit a pending matching-request outbox event.

**Implementation scope**

- Minimal FastAPI presign endpoint adapted to Lambda; presigned POST constraints and CORS.
- S3-triggered Python ingestion handler with streamed CSV validation, bounded errors, chunked/bulk inserts, batch/outbox transaction, and structured logs.
- Defer HMAC webhook delivery and its retry classification to M5; M3 does not dispatch the outbox.
- LocalStack S3 emulator and direct Lambda-handler event invocation; no cloud provisioning.

**Files to create/modify**

- `apps/api/` handlers/config/tests
- `services/ingestion/` configuration and streamed worker
- `tests/ingestion/` and `scripts/ingestion_e2e.py`
- README ingestion contract/error policy

**Acceptance criteria**

- Valid CSV creates one batch, its users, and one outbox event.
- Duplicate S3 delivery/webhook retry creates no duplicate users/events.
- File/header failures create no users; chosen row-error policy is consistent and visible.
- The pending outbox row contains only a batch identifier and is committed with batch completion; M5 will test n8n authentication and replay.

**Required tests:** Valid/boundary CSV, BOM/encoding, missing/extra columns, oversized file, duplicate IDs, DB rollback, concurrent/replayed event delivery, presigned POST, and local E2E. Webhook transport tests move to M5.

**Dependencies:** M2; finalized CSV schema and maximum byte/row counts.

**Definition of done:** Local end-to-end upload event simulation passes; handler is replay-safe; no eligibility logic exists in Lambda.

## M4 - Loan product discovery workflow

**Implementation note (2026-10-15):** Workflow A, its private Compose helper, two official source adapters, additive criterion-state/currency migration, fixture tests, and local live n8n execution are implemented. The original plan's `database/seeds/product_sources.*` was not added: allowlisted source rows are created transactionally at run start, avoiding duplicate configuration. No separate Gemini fixtures directory is needed because mock responses live in focused tests. HTTP conditional requests are deferred: sites did not expose a stable conditional-fetch contract in this verification, and unchanged parsed content is already deduplicated. Both live products are `review_required` because published conditions are incomplete; that is a deliberate fail-closed result, not a verified-match claim. See `docs/discovery-workflow.md` for remaining operational limits.

**Objective:** Build Workflow A for source-respectful, provenance-preserving discovery of verified product versions.

**Implementation scope**

- Select 2-3 accessible sources after terms/robots review; create per-source saved fixtures/adapters.
- n8n scheduled orchestration, rate limits, conditional requests, parser/extraction branch, Gemini Flash structured extraction adapter, deterministic validator, versioned persistence.
- Default tests use recorded fixtures and Gemini responses; live access is an explicit manual mode.

**Files to create/modify**

- `workflows/discovery.json`
- `services/discovery/` source adapters/Code-node sources, extraction schema/validator, prompt template/version (the tested source is embedded into the n8n export rather than reimplemented)
- `tests/fixtures/sources/`, `tests/fixtures/gemini/`
- `database/seeds/product_sources.*`
- docs/README source policy and workflow import instructions

**Acceptance criteria**

- Scheduled/manual fixture execution covers 2-3 sources and creates source-grounded current versions.
- Unchanged content is not versioned again; changed verified content creates one new current version.
- Missing/contradictory/hallucinated output cannot become a matchable product.
- Workflow export contains no credentials.

**Required tests:** Parser fixtures, layout failure, timeout/redirect/oversize/SSRF guard, JSON schema/evidence/range validation, invalid Gemini output, unchanged/changed version concurrency, workflow import.

**Dependencies:** M2; source/legal review; a free-tier or stubbed Gemini interface; no live paid call in CI.

**Definition of done:** Workflow and helpers are deterministic under fixtures, provenance is queryable, and failure leaves the last verified version intact but visibly stale.

## M5 - Optimized eligibility matching

**Implementation note (2026-10-15):** Workflow B, signed dispatcher, guarded synthetic fixtures, SQL-keyset pages, deterministic rules, optional capped advisory, completion outbox event, and local E2E are implemented. The earlier proposed n8n-native PostgreSQL node was replaced by a narrow private helper endpoint containing the version-controlled parameterized SQL; n8n still owns every stage and branch, while credentials remain out of the export. Synthetic demo rows are isolated by `upload_batches.is_demo` and `product_sources.source_type`. The implementation uses canonical-JSON HMAC because n8n exposes a parsed body. See the matching policy and workflow guide for remaining operational risks.

**Objective:** Build Workflow B and prove the multi-stage funnel is correct, bounded, idempotent, and measurable.

**Implementation scope**

- HMAC/timestamp/schema verification and atomic event claim.
- Parameterized SQL prefilter and bounded candidate paging.
- Version-controlled deterministic Code-node evaluator with golden tests.
- Guarded Gemini ambiguity branch, schema validation, caps/cache, fail-closed behavior.
- Bulk/idempotent match insertion, execution metrics, outbox reconciliation, and benchmark harness.

**Files to create/modify**

- `workflows/matching.json`
- `services/eligibility/sql/prefilter.sql`
- `services/eligibility/rules.*` (language chosen to be the same source embedded in the n8n Code node)
- `benchmarks/eligibility/`
- matching unit/integration/contract tests
- `docs/optimization-strategy.md` with measured results added only after execution

**Acceptance criteria**

- Pure numeric/categorical fixtures use zero LLM calls.
- Every qualified golden pair is inserted once with reason codes; failed/unknown pairs are not inserted.
- A full replay yields zero new matches and does not corrupt metrics/state.
- 10,000 × 50 benchmark completes within the post-baseline agreed local budget without unbounded n8n payload/memory.

**Required tests:** Threshold boundaries, all/any groups, missing fields, stale/unverified products, invalid operators, ambiguous admission/cap/cache/failure, duplicate/concurrent events, partial failure/rerun, query plan and benchmark correctness.

**Dependencies:** M2-M4; approved rule schema and unknown policy.

**Definition of done:** Workflow B export imports cleanly; benchmark raw data and environment are recorded; optimization claims are evidence-backed, not estimated as measurements.

## M6 - Notification workflow

**Objective:** Notify an owner-controlled test inbox exactly once per user/new-match group after successful matching.

**Implementation scope**

- Workflow C child-workflow invocation, grouping, text/HTML template, recipient redirect/allowlist, notification reservation, SES node, result logging.
- Local SES capture/stub; explicit sandbox live-test runbook.

**Files to create/modify**

- `workflows/notifications.json`
- `workflows/templates/matches.{txt,html}`
- notification query/source helpers if needed
- notification tests and README SES configuration

**Acceptance criteria**

- Sample CSV addresses can never become actual recipients in development/demo mode.
- Multiple new matches for a user produce one personalized test email.
- Rerun sends no duplicate; zero matches sends nothing.
- Definite SES failures retry safely; ambiguous outcomes are surfaced rather than blindly resent.

**Required tests:** Grouping, escaping, alias mapping, allowlist rejection, idempotency reservation, SES success/rejection/timeout, workflow chaining and no-op.

**Dependencies:** M5; verified SES sender/test inbox for the optional live run.

**Definition of done:** Captured local email is correct; one controlled SES sandbox email can be demonstrated when credentials are deliberately configured; logs contain no secret/full body.

## M7 - Frontend upload interface

**Objective:** Deliver the minimal, responsive primary interaction that starts the pipeline safely.

**Implementation scope**

- Next.js/TypeScript/Tailwind upload page with accessible file picker/drop zone, client-side advisory validation, direct S3 POST, progress, batch reference, and clear errors.
- Optional batch-status polling only if ENH-01 is approved and does not expand scope.

**Files to create/modify**

- `apps/web/app/`, components, API client, styles/config
- frontend unit/component/E2E tests
- README local run instructions

**Acceptance criteria**

- Keyboard/screen-reader usable; responsive at common mobile/desktop sizes.
- CSV bytes go from browser to S3/emulator, never through Next.js/FastAPI.
- No AWS secret appears in source, bundle, storage, or network request.
- Upload states distinguish validation, transfer, accepted, and failure.

**Required tests:** Component states, extension/type/size advisory checks, presign error, upload error/retry, E2E success, basic accessibility audit, responsive smoke.

**Dependencies:** M3 contracts; an emulator/fake upload target.

**Definition of done:** A fresh local run uploads a fixture and displays its batch reference; production build/lint/typecheck pass.

## M8 - AWS infrastructure configuration

**Objective:** Express a secure, cost-conscious, deployable AWS design without provisioning it by default.

**Implementation scope**

- Serverless configuration for bucket/event, Lambda functions/roles, Function URL or documented API Gateway selection, VPC/subnets/security groups, RDS, S3 gateway endpoint, secrets references, logs/retention, optional DLQ/alarms.
- Stage parameters, safe teardown notes, packaging exclusions, and current official cost estimate procedure.
- Document n8n host/network options; provision a host only if public deployment is explicitly approved.

**Files to create/modify**

- `infrastructure/serverless.yml`
- `infrastructure/config/*.yml` or documented parameters
- deployment/teardown runbooks and architecture updates
- static infrastructure tests

**Acceptance criteria**

- `serverless package`/config validation succeeds with placeholder parameters.
- IAM and security-group review shows least privilege, private RDS, encrypted storage, bounded logs, no plaintext secrets.
- Package contains only runtime files and pinned dependencies.
- No resource is deployed by CI or by completing this milestone unless explicitly authorized.

**Required tests:** Serverless print/package, policy lint, template assertions, secret scan, dependency/package size review.

**Dependencies:** M3-M7 handlers/contracts; current Serverless/AWS documentation; network/cost decision.

**Definition of done:** A reviewer can inspect exactly what would be created, configured, cost-bearing, and destroyed before choosing to deploy.

## M9 - Integration and end-to-end testing

**Objective:** Prove the complete pipeline under success, failure, and replay scenarios.

**Implementation scope**

- One-command local E2E harness and test data.
- Import all n8n workflows, trigger upload, discover fixture products, match, capture email.
- Failure injection at DB, webhook, crawl, Gemini, and SES boundaries.
- Optional tightly controlled AWS smoke if deployment is approved.

**Files to create/modify**

- `tests/e2e/`, orchestration scripts, sanitized fixtures
- CI integration job/artifact summaries
- operational runbook/troubleshooting section

**Acceptance criteria**

- Happy path produces expected database state and one captured email.
- Duplicate S3/webhook/workflow execution produces no duplicate user/match/email.
- Failed dependencies recover or land in a visible terminal state with a documented redrive.
- The assignment sample CSV is tested without emailing its addresses.

**Required tests:** Full happy path, empty/no-match, malformed batch, retries/replays, partial workflow failure, stale product, invalid LLM, SES ambiguity, concurrency smoke.

**Dependencies:** M1-M8; approved use of the provided sample file.

**Definition of done:** E2E evidence is repeatable from a clean checkout; all mandatory paths have automated or explicitly documented manual evidence.

## M10 - Documentation and submission readiness

**Objective:** Produce an understandable, defensible submission and verify every requirement before owner-controlled delivery.

**Implementation scope**

- Final README setup/deploy/credentials/workflow/design/optimization documentation and updated Mermaid diagrams.
- Requirement traceability audit and limitations/open-question resolution.
- 5-10 minute video script/checklist and recorded demonstration evidence.
- Repository hygiene, license/attribution, dependency/secret scan, collaborator/submission checklist.

**Files to create/modify**

- `README.md`, `docs/*.md`, `docs/demo-script.md`, `docs/runbooks/`
- final workflow exports and version manifest
- submission checklist (no credentials or private links committed)

**Acceptance criteria**

- Every mandatory requirement maps to implemented, tested evidence or is prominently identified as unmet.
- A new reviewer completes local setup from README without tribal knowledge.
- Video covers each n8n workflow/node, live E2E, and received test email within 5-10 minutes.
- Private repository collaborator list exactly matches the assignment before submission.

**Required tests:** Clean-clone rehearsal, link/command validation, final CI/E2E, secret scan, workflow re-import, packaged infrastructure validation.

**Dependencies:** M1-M9; assignment-email timestamp and owner access to GitHub, inbox, recorder, and submission form.

**Definition of done:** Review checklist is signed off; repository and video links are ready. Inviting collaborators, committing/pushing, recording, and submitting remain explicit owner-authorized actions.

## Recommended next step

Begin M1 with a small reviewable change that pins runtime/tool versions and starts only PostgreSQL plus n8n locally. Before M2, resolve the six open requirement/database questions—especially partial-row acceptance and the n8n cloud-demo placement—because they affect state transitions and test contracts.

