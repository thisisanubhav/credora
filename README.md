# Loan Eligibility Engine

An event-driven platform that ingests CSV batches, discovers personal-loan products, evaluates eligibility, and sends test notifications through workflows orchestrated by self-hosted n8n.

> **Current phase:** M2 database foundation. Local PostgreSQL and n8n are running; the application schema, migrations, and integrity tests are implemented. API endpoints, ingestion, workflows, frontend, AWS resources, and paid integrations are not implemented or provisioned.

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
│   └── docker-compose.yml      # PostgreSQL and n8n local services
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

## Local development (M1)

### Prerequisites

- Docker Engine/Desktop with Compose v2 or newer, running locally. M1 was verified with Docker Engine 29.4.0 and Compose 5.1.2.
- Python 3.9+ for the standard-library-only environment and smoke scripts. M2 Python models and tests require Python 3.12+; `.python-version` selects 3.12. On this host, `python3` resolves to 3.9.6, while `python3.12` is installed separately (3.12.14).
- `uv` for the locked M2 Python dependencies. Run `uv sync --frozen` once after checkout; `uv run --frozen` in the Make targets then uses the local environment.
- `make` for the root commands. Equivalent Docker Compose commands are shown below.
- Node is not needed to start M1. Frontend work in M7 uses Node 24 LTS, selected in `.nvmrc`. The current host's Node 25 is end of life and should be switched before M7.

The containers are pinned to `postgres:16.15-bookworm` and `n8nio/n8n:2.43.5`. PostgreSQL 16 and n8n 2.43.5 both publish arm64 and amd64 images. n8n 2.43.5 is a stable release and supports PostgreSQL persistence and the `/healthz` endpoint. See the [PostgreSQL image tags](https://hub.docker.com/_/postgres), [n8n Compose guide](https://docs.n8n.io/deploy/host-n8n/install-options/use-a-cloud-provider/use-docker-compose/), [n8n database settings](https://docs.n8n.io/deploy/host-n8n/configure-n8n/basic-configuration/use-environment-variables/database/), and [n8n endpoint settings](https://docs.n8n.io/deploy/host-n8n/configure-n8n/basic-configuration/use-environment-variables/endpoints/).

### First start

From the repository root:

```sh
make init       # Create ignored .env with three independent random local secrets
make config     # Validate environment and Compose configuration without printing secrets
make up         # Start PostgreSQL, wait for health, then start n8n and wait for health
make smoke      # Check both databases, authentication, HTTP, networking, volumes, bindings
```

`make init` refuses to overwrite an existing `.env`. `.env` is gitignored and created with mode `0600`. Review non-secret settings in [.env.example](.env.example) before starting; the generator fills only `POSTGRES_PASSWORD`, `N8N_DB_PASSWORD`, and `N8N_ENCRYPTION_KEY`. Keep the encryption key stable as long as the n8n database and volume are retained, or stored n8n credentials may become unreadable. The local environment uses `N8N_SECURE_COOKIE=false` only because its endpoint is loopback HTTP; a public deployment needs HTTPS and a different security configuration.

| Variable | Purpose |
|---|---|
| `COMPOSE_PROJECT_NAME` | Names this checkout's Compose containers, network, and volumes. Change it if another checkout uses the same name. |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | Application database and local bootstrap/migration administrator. Do not use this role in application runtime. |
| `POSTGRES_PORT` | Host-side PostgreSQL port on `127.0.0.1`; container port is always 5432. |
| `APP_DB_USER`, `APP_DB_PASSWORD` | Restricted application DML login, provisioned by `make db-role`; not the n8n internal login. |
| `TEST_DB_NAME` | Dedicated migration/integrity test database, required to end in `_test`. |
| `N8N_DB_NAME`, `N8N_DB_USER`, `N8N_DB_PASSWORD` | Separate n8n internal database and login, created only on first PostgreSQL volume initialization. |
| `N8N_HOST`, `N8N_PORT`, `N8N_PROTOCOL`, `N8N_WEBHOOK_URL` | Loopback editor URL and local webhook base URL; the validation script keeps them consistent. |
| `N8N_ENCRYPTION_KEY` | Stable key for n8n credential encryption. Never commit or rotate casually. |
| `GENERIC_TIMEZONE` | Timezone for n8n schedules; UTC by default. |

PostgreSQL initializes both databases in UTF-8. The official entrypoint creates `loan_engine`; `infrastructure/postgres/init/01-create-n8n-db.sh` creates `n8n` and its restricted login. The script runs when the named PostgreSQL volume is empty. Existing volumes are not reinitialized by `make up`, so editing database names or passwords in `.env` after first start does not change existing database credentials. The n8n data directory and PostgreSQL data each use a named volume.

### Access, inspection, and shutdown

- Open the n8n editor at <http://localhost:5678> (or the configured local `N8N_PORT`). Complete n8n's first-run owner setup locally. No workflows are installed yet.
- Connect a database client to `127.0.0.1:5432` (or `POSTGRES_PORT`). Use the application database name and local bootstrap login from `.env`. Inside Compose, the host is `postgres` and the port is `5432`. n8n itself uses its separate `N8N_DB_NAME` and `N8N_DB_USER`.
- `make status` shows container state and health. `make logs` follows the last 100 log lines; stop following with Ctrl+C. Logs should not contain credentials; do not paste private log output into public issues.
- `make down` stops and removes containers/network while preserving both data volumes. `make up` reuses them.

The equivalent Compose invocation from the repository root is:

```sh
docker compose --project-directory . --env-file .env -f infrastructure/docker-compose.yml ps
```

To erase **only this Compose project's local PostgreSQL and n8n data**, first check `COMPOSE_PROJECT_NAME` in `.env` and run the command below from this repository root. This permanently removes local databases, n8n users, workflows, and encrypted credentials; `make down` alone does not.

```sh
docker compose --project-directory . --env-file .env -f infrastructure/docker-compose.yml down --volumes
```

### Troubleshooting

| Symptom | Check |
|---|---|
| `make up` cannot connect to Docker | Start Docker Desktop/daemon and run `docker info`. `make config` can still validate Compose syntax without the daemon. |
| Port 5432 or 5678 already in use | Set a free `POSTGRES_PORT` or `N8N_PORT` in `.env`; update `N8N_WEBHOOK_URL` to the matching localhost URL, then rerun `make config`. |
| PostgreSQL is healthy but n8n fails to connect | Read `make status` and `make logs`. Verify `N8N_DB_*` values match the credentials used when the PostgreSQL volume was first initialized. |
| n8n starts but `/healthz` fails | Wait for database migrations, then inspect `make logs`; n8n may need longer on its first run. |
| Changed encryption key after first run | Restore the original ignored `.env` value. Regenerating the key does not decrypt stored credentials. |
| Changed database name/password after first run | Restore the original `.env`, or deliberately reinitialize the project's volumes after backing up wanted data. The init script is not a migration tool. |

### Database foundation (M2)

For an existing M1 checkout, run `python3 scripts/local_env.py extend` once. It appends only the new M2 settings and a random runtime password to the ignored `.env`; it does not overwrite the three existing local secrets. New checkouts receive all settings from `make init`. Then, from the repository root:

```sh
uv sync --frozen
make up
make db-upgrade   # Apply Alembic revisions to the application database as bootstrap owner
make db-role      # Create/refresh restricted application runtime permissions
make db-connect   # Verify runtime connectivity and absence of DDL/DELETE privileges
make db-status    # Display the applied Alembic revision
make db-test      # Create/validate dedicated *_test DB; round-trip migrations there
make lint
make typecheck
make smoke        # Recheck the M1 containers and database isolation
```

`make db-test` downgrades and rebuilds schema **only** in `TEST_DB_NAME`; it never targets `POSTGRES_DB` or the n8n database. It removes previous test data. The application migration is non-destructive on upgrade; do not run `alembic downgrade base` on a database containing wanted data. `make db-role` is idempotent and should be rerun after future migrations. It grants DML without DDL/DELETE and permits product lifecycle metadata updates but not edits to historical eligibility rules. Database and test credentials remain only in ignored `.env` (mode `0600`); Alembic's INI contains no URL.

The schema has nine application tables: the eight planned entities plus `notification_matches`, a join table that enforces match-to-notification foreign keys and at-most-one notification reservation per match. Product versions retain source evidence and a rule document. Unknown criteria are explicit and cannot be marked verified as an empty document. `matches.status = 'potential'` is **not** approval. See [M2 design decisions and query/index examples](docs/database-design.md#m2-implementation-review-2026-10-15). No real user or loan data is seeded.

The next implementation milestone is **M3: CSV ingestion**. M2 does not parse CSV, crawl sites, match users, or send email.

