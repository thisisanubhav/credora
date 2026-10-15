# Requirements and Traceability

## Source and interpretation policy

This analysis is based on all four pages of **The Loan Eligibility Engine (Engineering Intern)** assignment, exported from the provided Google Doc as a PDF on 2026-10-15, plus the narrower technology and quality constraints in the project brief.

The source hierarchy used here is explicit:

- **Mandatory - assignment:** stated as “must,” “will need,” or a deliverable in the assignment.
- **Mandatory - project brief:** an additional constraint chosen by the stakeholder for this implementation. It may narrow an option allowed by the assignment.
- **Optional - assignment:** explicitly described as optional or a plus.
- **Proposed enhancement:** a design choice, not an assignment requirement. Enhancements may be removed if time threatens mandatory scope.

Nothing marked “proposed” should be represented as completed until implemented and tested.

## Functional requirements

| ID | Class | Requirement | Acceptance evidence |
|---|---|---|---|
| FR-01 | Mandatory - assignment | Accept a bulk CSV containing user data such as `user_id`, `email`, `monthly_income`, `credit_score`, `employment_status`, and `age`. | Valid sample CSV is accepted; row-level validation behavior is documented and tested. |
| FR-02 | Mandatory - assignment | Use a robust, scalable ingestion pattern rather than sending the CSV body through a normal Lambda-backed API Gateway request. | UI uploads directly to object storage with a short-lived presigned request; object creation triggers processing. |
| FR-03 | Mandatory - assignment | Parse uploaded users and persist them in a dedicated PostgreSQL table on Amazon RDS in the AWS design. | Integration test verifies a batch and its valid users are committed; deployment template declares RDS. |
| FR-04 | Mandatory - assignment | Run self-hosted n8n using Docker and orchestrate all core business workflows through n8n. | Compose configuration starts n8n; exported workflow JSON and execution evidence exist for A, B, and C. |
| FR-05 | Mandatory - assignment | Workflow A runs on a schedule and crawls 2-3 chosen public financial websites. | Active Schedule Trigger, allowlisted sources, and a recorded execution covering 2-3 sources. |
| FR-06 | Mandatory - assignment | Extract product name, interest rate, and eligibility criteria, then store structured products in `loan_products`. | Source-grounded extraction fixture and database rows with provenance. |
| FR-07 | Mandatory - assignment | Workflow B is triggered by webhook after a new user CSV has been successfully processed. | Authenticated webhook receives a committed batch ID only after ingestion succeeds. |
| FR-08 | Mandatory - assignment | Workflow B fetches newly added users and all available product criteria, implements matching in n8n, and stores every successful user-product link in `matches`. | Batch-scoped execution produces correct, idempotent rows from deterministic fixtures. |
| FR-09 | Mandatory - assignment | Implement a multi-stage optimized filter that reduces user-product pairs before any qualitative LLM checks. | Metrics show counts at each stage; benchmark compares the specified strategies without fabricated results. |
| FR-10 | Mandatory - assignment | Workflow C runs after Workflow B and constructs a personalized email for each user with new matches. | Workflow chaining and template tests group new matches once per user. |
| FR-11 | Mandatory - assignment | Send through the AWS SES node in n8n to controlled test inbox aliases; never send to sample CSV addresses. | Delivery guard rewrites/blocks recipients, SES sandbox configuration is documented, and a test email is shown in the video. |
| FR-12 | Mandatory - assignment | Provide a minimal UI whose primary action is uploading the initial user CSV. | Responsive upload page completes a valid direct-to-S3 upload and reports transfer acceptance plus a batch reference; processing status is optional ENH-01. |
| FR-13 | Mandatory - project brief | Use Gemini Flash for the limited tasks that genuinely require an LLM, request structured JSON, and validate it deterministically. | Model output passes a versioned Pydantic/JSON Schema or is rejected; raw source evidence is retained. |
| FR-14 | Mandatory - project brief | Do not use an LLM for simple numeric comparisons and never fabricate eligibility criteria. | Numeric rules are deterministic; missing/unsupported criteria remain unknown and cannot produce an automatic eligible result. |
| FR-15 | Mandatory - project brief | Associate every uploaded user with its CSV upload batch. | Non-null `users.upload_batch_id` FK and within-batch duplicate constraint. |

## Technical and quality constraints

| ID | Class | Constraint |
|---|---|---|
| TC-01 | Mandatory - assignment | AWS design uses Lambda, RDS for PostgreSQL, and SES. |
| TC-02 | Mandatory - assignment | Use Serverless Framework for AWS resource definitions and Docker Compose for n8n. |
| TC-03 | Mandatory - project brief | Python 3.12+, SQLAlchemy, Pydantic, and FastAPI where appropriate; frontend uses Next.js, TypeScript, and Tailwind CSS. |
| TC-04 | Mandatory - project brief | Services must be independently testable; prioritize reliability, scalability, security, maintainability, and interview clarity. |
| TC-05 | Mandatory - project brief | Never commit credentials or secrets. |
| TC-06 | Mandatory - project brief | Initial development must not require paid cloud resources, provision AWS resources, deploy, or make paid API calls. |
| TC-07 | Mandatory - project brief | Avoid unnecessary infrastructure and features that do not improve the assignment. |
| TC-08 | Mandatory - project brief | Stop this phase after planning and initial repository foundation; do not implement business functionality or migrations yet. |

The assignment permits Python **or Go** and any accessible LLM; TC-03 and FR-13 are deliberate stakeholder selections, not claims about the original PDF.

## Deliverables

| ID | Class | Deliverable | Planned location/evidence |
|---|---|---|---|
| DEL-01 | Mandatory - assignment | Private GitHub repository with all source and configuration; invite `ujjwalkala-clickpe`, `HarshSrivastav-Dailype`, `ManishBiswal-clickpe`, and `tushar-clickpe`. | Final repository settings; this phase does not create/invite/commit/push. |
| DEL-02 | Mandatory - assignment | `serverless.yml` declaring all required AWS resources. | `infrastructure/serverless.yml` in M8. |
| DEL-03 | Mandatory - assignment | `docker-compose.yml` for self-hosted n8n. | `infrastructure/docker-compose.yml` in M1. |
| DEL-04 | Mandatory - assignment | JSON exports for each n8n workflow. | `workflows/discovery.json`, `matching.json`, `notifications.json`. |
| DEL-05 | Mandatory - assignment | Comprehensive README with architecture diagram, AWS/n8n setup and deployment, credential configuration, design decisions, crawl strategy, and optimization explanation. | README expanded incrementally; detailed supporting docs linked from it. |
| DEL-06 | Mandatory - assignment | A 5-10 minute video walking through every n8n node, demonstrating the pipeline live end-to-end, and showing a received test email. | Final submission evidence in M10. |
| DEL-07 | Mandatory - assignment | Submit repository and video links through the provided form within 72 hours of receiving the assignment email. | Owner action; exact deadline depends on email receipt time. |
| DEL-08 | Mandatory - assignment | Test with the provided `users.csv`. | Sanitized fixture derived from the supplied file plus recorded E2E run; redistribution/license checked first. |

## Evaluation criteria

| Category | Points | What must be demonstrated |
|---|---:|---|
| n8n Workflow Design & Automation | 30 | Sophisticated, robust, efficient workflows; creative but maintainable nodes for crawling, manipulation, and logic; strong optimization solution. |
| Cloud Architecture & Integration | 20 | Sound serverless design, secure/seamless AWS-to-self-hosted-n8n boundary, scalable ingestion. |
| Backend Functionality & Code Quality | 30 | Correct ingestion, clean modular code, useful comments rather than commentary noise. |
| Documentation & Presentation | 20 | Clear architecture diagram/README and a comprehensive, convincing demo video. |
| **Total** | **100** | Mandatory behavior matters more than optional polish. |

## Optional items stated by the assignment

| ID | Item | Decision |
|---|---|---|
| OPT-01 | API Gateway is optional. | Start with a Lambda Function URL for the small FastAPI presign API only if its access controls suffice; retain API Gateway as a documented swap if authentication, WAF, usage plans, or richer routing become necessary. |
| OPT-02 | Local deployment is acceptable; public AWS deployment is a plus, not required, and cloud spend is not expected. | Local-first. Produce deployable configuration without deploying during initial development. |
| OPT-03 | Handling changes in source website layout is optional. | Add fixtures, selectors, provenance, and failure alerts; do not build a generalized anti-breakage crawler. |

## Proposed enhancements (not assignment requirements)

| ID | Enhancement | Justification / scope guard |
|---|---|---|
| ENH-01 | Upload status endpoint and UI progress states. | Improves operability; keep to batch status only, not a general admin portal. |
| ENH-02 | Transactional workflow outbox plus a small reconciliation schedule. | Prevents a committed batch from being stranded when the n8n webhook is temporarily unreachable. Reuse PostgreSQL; do not add Kafka. |
| ENH-03 | Lambda dead-letter queue and structured alarms in the production template. | Gives failures a durable recovery path; omit from local runtime. |
| ENH-04 | Versioned product rules and source snapshots/hashes. | Makes matches reproducible and prevents silent changes or invented criteria. |
| ENH-05 | Dry-run email mode and hard recipient allowlist/redirect. | Prevents accidental mail to sample users and supports safe demos. |
| ENH-06 | Lightweight execution metrics per filtering stage. | Makes the optimization claim measurable without storing rejected Cartesian pairs. |

## External dependencies

| Dependency | Purpose | Local/free path | Risk/constraint |
|---|---|---|---|
| Amazon S3 | Direct CSV storage and event source | LocalStack or a filesystem-backed adapter may be evaluated in M1; unit tests use fakes. | Events are at-least-once; validate file size/type and object key. |
| AWS Lambda | Presign API and CSV processor | Python functions run directly or through Serverless offline where useful. | Time, memory, `/tmp`, VPC cold-start, and database-connection limits. |
| Amazon RDS PostgreSQL | Persistent users, products, matches, and operational records | PostgreSQL container. | Private networking and connection pressure; consider RDS Proxy only if measurements justify it. |
| AWS SES | Test email transport from n8n | n8n execution can use a mock/capture service locally; SES sandbox for real demo. | Verified identity/sandbox recipients, region alignment, quotas. |
| Self-hosted n8n | Workflow orchestration | Docker Compose. | Must be reachable from AWS for a deployed webhook; protect editor and webhook separately. |
| Gemini Flash API | Structured extraction and rare ambiguous checks | Fixtures/stub by default; free tier only if deliberately enabled. | Model/version drift, quotas, prompt injection in scraped text, unverifiable output. |
| Public financial websites (2-3) | Product source material | Saved HTML fixtures for tests. | Terms, robots policy, rate limits, layout changes, and source accuracy. |
| Next.js/Tailwind | Minimal browser UI | Local Node runtime. | Keep dependencies and bundle small. |
| Serverless Framework | Infrastructure definition/deployment | Package/validate locally. | Version/license/plugin compatibility must be pinned before M8. |
| GitHub and Google submission form | Required delivery | Private repository and owner submission. | Collaborator invitations and submission are explicit owner-controlled actions. |

## Requirement-to-implementation traceability matrix

“Planned” means design coverage only in this phase.

| Requirement | Component / artifact | Verification | Milestone | Status |
|---|---|---|---|---|
| FR-01, FR-02, FR-12 | `apps/web`, `apps/api`, S3 presigned POST | UI/E2E upload; policy and file-limit tests | M3, M7 | Planned |
| FR-03, FR-15 | Ingestion Lambda, `upload_batches`, `users` | PostgreSQL integration tests; duplicate/retry tests | M2, M3 | Planned |
| FR-04 | Docker Compose and three n8n JSON exports | Compose healthcheck; workflow import and execution tests | M1, M4-M6 | Planned |
| FR-05, FR-06 | Workflow A, discovery helpers, `product_sources`, `loan_products` | Saved-source fixtures, schema validation, provenance assertions | M4 | Planned |
| FR-07 | Signed n8n webhook and `workflow_outbox` | Invalid signature/replay/retry tests | M3, M5 | Planned |
| FR-08 | Workflow B, eligibility package, `matches` | Golden eligibility cases; idempotent rerun test | M5 | Planned |
| FR-09, FR-14 | SQL prefilter + deterministic engine + bounded ambiguity path | Reproducible benchmark and “zero LLM for numeric rules” assertion | M5 | Planned |
| FR-10, FR-11 | Workflow C, `notification_logs`, SES node | Template, recipient-safety, retry, and duplicate-send tests | M6 | Planned |
| FR-13 | Gemini adapter and versioned extraction schema | Contract fixtures, invalid JSON/missing-evidence/fail-closed tests | M4, M5 | Planned |
| TC-01, TC-02 | `serverless.yml`, Compose, n8n exports | Static validation and deployment package test | M8 | Planned |
| TC-03, TC-04 | Python packages, FastAPI, Next.js, test suites | Lint, type checks, unit/integration/contract tests | M1-M9 | Planned |
| TC-05, TC-06, TC-07 | `.gitignore`, `.env.example`, local-first design | Secret scan; clean setup; architecture review | M1, M10 | Foundation started |
| DEL-01-DEL-08 | Repository, docs, configs, exports, video checklist | Submission-readiness audit | M10 | Planned |

## Open requirement questions

1. The source says “likely eligible” but does not define whether unknown criteria should be included. This design fails closed: unknown or unverified criteria do not create an automatic match. Confirm before implementation.
2. The exact 2-3 websites are not prescribed. They must be selected after checking public accessibility, robots guidance, terms, stable product pages, and whether their wording can be cited as provenance.
3. The exact CSV schema, maximum size, invalid-row policy, and whether partial batch acceptance is allowed are unspecified. The proposal is a versioned required schema, configurable size cap, whole-batch rejection for header/file errors, and row-level rejection with counts for data errors.
4. A deployment location for self-hosted n8n is not prescribed. Local is acceptable; if an AWS end-to-end demo is desired, n8n needs an HTTPS-reachable host and private or tightly restricted database connectivity.
5. The assignment asks for “all required AWS resources” in `serverless.yml`, but RDS/VPC through Serverless can make teardown costly and slow. The plan still models them there, with safe parameters and no deployment by default.
6. The 72-hour deadline cannot be calculated without the assignment-email receipt timestamp.

