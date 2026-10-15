# Loan Eligibility Engine

An event-driven platform that ingests CSV batches, discovers personal-loan products, evaluates eligibility, and sends test notifications through workflows orchestrated by self-hosted n8n.

> **Current phase:** architecture and planning only. No application services, workflows, AWS resources, or paid integrations have been implemented or provisioned.

## Planned flow

1. A Next.js UI requests a short-lived presigned S3 upload and sends the CSV directly to S3.
2. An S3 `ObjectCreated` event invokes a Python ingestion Lambda.
3. The Lambda validates the CSV and atomically persists an upload batch and its users in PostgreSQL.
4. After commit, the Lambda invokes an authenticated n8n matching webhook with a batch identifier.
5. n8n runs set-based SQL pre-filtering, deterministic rules, and only then any necessary bounded LLM checks.
6. Qualified matches are persisted idempotently; a notification workflow groups new matches by user and sends only to controlled test aliases through AWS SES.
7. Separately, a scheduled n8n workflow discovers products from an allowlist of public sources, extracts source-grounded criteria with Gemini Flash where useful, validates the JSON deterministically, and upserts versioned products.

See the [architecture](docs/architecture.md) for diagrams and failure handling.

## Documentation

- [Requirements and traceability](docs/requirements.md)
- [Architecture](docs/architecture.md)
- [Database design](docs/database-design.md)
- [Optimization strategy](docs/optimization-strategy.md)
- [Development roadmap](docs/development-roadmap.md)

## Proposed repository layout

```text
.
├── apps/
│   ├── api/                    # Presign HTTP API; optional batch status later
│   └── web/                    # Minimal Next.js upload UI
├── services/
│   ├── ingestion/              # S3-triggered CSV validation and persistence
│   ├── discovery/              # Testable parser/Code-node sources used by n8n
│   └── eligibility/            # Version-controlled SQL/Code-node sources used by n8n
├── workflows/
│   ├── discovery.json          # Workflow A export
│   ├── matching.json           # Workflow B export
│   └── notifications.json      # Workflow C export
├── database/
│   ├── migrations/             # Alembic migrations
│   └── seeds/                  # Local-only deterministic fixtures
├── infrastructure/
│   ├── serverless.yml          # AWS declarations; no deployment is performed by default
│   └── docker-compose.yml      # PostgreSQL, n8n, and local development dependencies
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── contract/
│   └── e2e/
└── docs/
```

This is a modular monorepo, not a set of independently deployed microservices. `services/` contains reusable, independently testable backend packages plus the version-controlled SQL/Code-node sources embedded in n8n exports; n8n remains the business-workflow orchestrator. The split keeps Lambda handlers thin and prevents workflow logic from becoming unreviewable or duplicated.

| Directory | Why it exists |
|---|---|
| `apps/` | User-facing deployable entry points: the small HTTP API and web UI. |
| `services/` | Testable ingestion/discovery modules and n8n-owned eligibility source artifacts, without forcing separate deployments. |
| `workflows/` | Reviewable, importable n8n JSON plus version-controlled templates. |
| `database/` | Schema evolution and explicitly local/test seed data. |
| `infrastructure/` | Keeps cloud and local runtime declarations separate from application logic. |
| `tests/` | Separates fast logic checks, real-PostgreSQL integration, boundary contracts, and end-to-end evidence. |
| `docs/` | Holds the architectural reasoning and traceability that would make the implementation defensible in review. |

## Development status

The next recommended milestone is **M1: repository and local infrastructure**. Its exact scope and definition of done are in the [roadmap](docs/development-roadmap.md). Do not place real credentials in this repository; future local setup will start from `.env.example`.

