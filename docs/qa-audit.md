# M9 assignment coverage and QA scope

Source of truth: the four-page `tmp/pdfs/assignment.pdf` supplied with the project, plus actual handlers, n8n exports, migrations and local executions on 2026-10-15. Status applies to **assignment deliverables**, not just whether a unit test exists. Local deployment is explicitly acceptable in the PDF; AWS RDS/SES evidence cannot be inferred from Docker or mocks.

| Assignment requirement / deliverable | Observed implementation and M9 evidence | Status |
|---|---|---|
| Bulk CSV upload without API Gateway body transfer | Real Chromium browser requested a presigned POST and transferred to LocalStack S3 directly; API receives metadata only. | PASS (local) |
| Event-driven S3 ingestion / Lambda | Same handler consumed native-shaped S3 event locally; AWS S3 notification is declared but no Lambda/S3 resource was deployed. Local bridge polls emulator objects. | PARTIAL |
| Users persisted in RDS PostgreSQL | Real PostgreSQL 16 contains batch-scoped users; 10,000-row ingestion benchmark passed. It is local Docker, **not RDS**. | BLOCKED_BY_ZERO_BUDGET for RDS |
| Self-hosted Docker n8n | n8n 2.43.5 healthy on loopback, workflows imported and B/C published; internal PG16 compatibility warning remains. | PASS (local) |
| Workflow A daily schedule and two/three public sources | Daily trigger present but inactive by default; manual real n8n run fetched SBI and Axis, both outcomes `unchanged`, run `succeeded`; source records remain `review_required`. | PARTIAL (schedule inactive) |
| Source-grounded product fields/criteria | Two current official products and version/provenance persisted; missing conditional facts remain unknown, never invented. | PASS (local) |
| LLM API for specific AI extraction | Gemini adapter, strict schema and negative tests exist; no API key/live call was available or made. Deterministic extraction proceeded. | NOT_TESTED live |
| Webhook-triggered Workflow B after processed CSV | Real browser batch outbox delivered through signed dispatcher into n8n B. App-side matching run `1a29136f-b443-4d4b-93bf-2e0feb99d13e` succeeded, but n8n's corresponding webhook execution remains `running` with no stop time. | PARTIAL |
| Optimized filter rather than LLM per pair | Actual sample: 500,000 theoretical pairs → 100,499 SQL candidates, deterministic run 8.058 s, zero LLM calls. Only synthetic products were used. | PASS (local strategy B) |
| Persist successful matches | Real browser batch persisted 3 version-linked synthetic matches; live SBI/Axis products did not match automatically. | PASS (local) |
| Workflow C after B; personalized grouped message | App-side C run `6bf16ae6-425b-45e9-8822-ede99929053d` recorded two grouped mock notifications for three matches; an unmatched user received none. n8n's own webhook execution remains `running`; no real email was sent. | PARTIAL |
| AWS SES node, test inbox aliases, received email | Export contains the actual SES node, but local execution took the mock branch. No AWS credentials, SES send, inbox receipt or video evidence. | BLOCKED_BY_ZERO_BUDGET |
| Minimal upload UI | Next.js/TypeScript/Tailwind page passed desktop, tablet, mobile, keyboard, progress, failure/retry and row-error tests; real browser batch `72a0cb08-0d1a-47e8-b846-73d9efcdbe76`. | PASS (local) |
| `serverless.yml`, Compose, three workflow JSON exports | Files exist; offline template/artifact checks, Compose smoke and real workflow imports pass. Serverless CLI cloud resolution/deploy was not run. | PARTIAL |
| README architecture/setup/design explanations | Documents and Mermaid diagram exist; M9 adds audit evidence. Future AWS deployment prerequisites remain conditional. | PASS for local setup; PARTIAL for cloud validation |
| Private GitHub repo and four collaborator invitations | Repository URL was supplied in prior context; M9 made no GitHub API call, push or collaborator verification. Local branch remains unpushed. | NOT_TESTED |
| 5–10 minute video and received-email demonstration | Not produced during M9; real email is prohibited by zero budget. | BLOCKED_BY_ZERO_BUDGET / NOT_TESTED video |
| Submission form within 72 hours | No form submission was authorized or attempted. | NOT_TESTED |

The scored categories in the PDF (n8n 30, cloud 20, backend 30, documentation/presentation 20) are **evaluation weights**, not a self-awarded score. A numeric score would be misleading while SES receipt/video/cloud integration remain incomplete.

## QA execution coverage

- Ingestion: 23 real PostgreSQL/LocalStack tests cover row/file errors, duplicates, 10k chunking, rollback, concurrency, S3 events, size, logging, API metadata and AWS ownership; browser test covered direct transfer. Invalid `.invalid` fixture emails were correctly rejected in the first QA attempt.
- Matching: 17 tests cover numeric boundaries, currency, unknowns, review-required real products, SQL paging, persistence, signed replay and dispatcher concurrency/retry. Real n8n browser batch yielded 3 synthetic matches, 0 LLM calls.
- Notifications: 9 tests cover grouping, reservation concurrency, recipient isolation, ambiguous acceptance, mock vs SES state, unverified products and signed event type. Real n8n C used mock only.
- Failure injection: n8n stop left a ready outbox row pending with `retry_count=1`/`webhook_transport_or_response`; restart advanced it to delivered with `retry_count=2` and one succeeded matching run. OrbStack shutdown interrupted PostgreSQL/LocalStack and local workers; `make up`/`make s3-init` recovered infrastructure, but a missing emulator object requires re-upload.
- Frontend: Playwright checks responsive overflow (390/768 px), keyboard focus, drag/drop, bounded polling, duplicate submit, expiry simulation, backend failures and row-error pagination. The real browser page emitted no uncaught page errors.

See [security audit](security-audit.md), [performance report](performance-report.md), [bug fixes](bug-fixes.md), and [test evidence](final-test-evidence.md). No M10 submission work was started.
