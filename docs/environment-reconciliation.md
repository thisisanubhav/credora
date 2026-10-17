# Local environment reconciliation — 2026-10-17

## Canonical development environment

Use `/Users/anubhav/.superset/worktrees/Loan Engine/enthusiastic-space-05804b95` on branch `feat/aws-ses-final-test-preparation`. This worktree contains the latest SES recovery implementation and the existing populated Docker Compose project `loan-eligibility-engine`. Its PostgreSQL database, n8n database, and named volumes are the authoritative local state. The other worktree at `/Users/anubhav/.superset/worktrees/Loan-Engine/abounding-apple-8e067784` is branch `restart-workspace-8e067784` at the older remote baseline. Its Compose project `loan-engine-8e067784` has a separate, empty application database. No database rows or n8n records were merged or copied between the stacks.

| Service | Canonical address | Ownership |
|---|---|---|
| Frontend | <http://127.0.0.1:3107> | `make web-dev` from the SES worktree |
| FastAPI | <http://127.0.0.1:8000/health> | `make api` from the SES worktree |
| n8n | <http://127.0.0.1:5678> | Compose project `loan-eligibility-engine` |
| PostgreSQL | `127.0.0.1:5432` | Same Compose project; application and n8n databases are separate |
| LocalStack | `http://127.0.0.1:4566` | Same Compose project; local emulator only |
| Internal discovery helper | Compose network only, port 8001 | Same Compose project |
| Ingestion worker | No listening port | `make local-worker` from the SES worktree |
| Notification dispatcher | Stopped | Leave stopped while SES records remain ambiguous |

The old worktree used PostgreSQL 5433, n8n 5679, and LocalStack 4567. Its frontend, API, worker, and dispatcher were identified by their Superset terminal sessions and stopped. Its four Compose containers were subsequently stopped without removing containers, networks, or volumes. Its Docker volumes remain intact. Do not start its frontend or API on the shared ports; do not point the SES worktree at its empty database.

## Preservation and verification

Before service reconciliation, private local backups of the canonical application database, n8n database, PostgreSQL globals, n8n data volume, LocalStack volume, and ignored `.env` were placed outside Git at `/Users/anubhav/.superset/backups/loan-engine-ses-20261017T072915Z` with directory mode 0700 and files mode 0600. Archive checksums and dump/archive inventories were verified. This backup contains sensitive local state; keep it private and never add it to this repository.

After reconciliation, the application database remained at Alembic `9187e3f76a21` with 35 batches, 81 users, 7 loan product versions, 43 matches, 32 notifications, 58 outbox events, and 68 workflow records. All 58 outbox events were delivered. The two SES notification records remained `ambiguous`, each with one attempt and no SES Message ID. Event `28468b63-316a-53e7-ac10-450ebba1c17c` remained delivered with retry count 2 and `targeted_only` recovery scope; notification `d27db780-33fd-47a3-a13e-d4579d3bb7f7` remained ambiguous. Preparation audit `f05e5449-5987-46e1-b0b1-54478b572a51` and release audit `a3da1020-0d39-4f0b-9c89-9ea1ff67c52d` remained present. n8n Workflows A/B/C remained published, with existing latest executions 172/175/177 respectively. Execution 177 is terminal `success` because the workflow handled the SES node's `Forbidden` response; it is not proof of SES delivery.

## Safe local operation

From the canonical worktree, `make status` and `make smoke` inspect the Compose stack. If the existing containers are stopped, `make up` reuses their named volumes. Start the API, ingestion worker, and frontend in separate supervised terminals with `make api`, `make local-worker`, and `make web-dev`. Stop only those host processes with Ctrl+C in their own terminals. `make down` removes containers and network while retaining named volumes, but is unnecessary for normal development. Never use `down -v`, volume pruning, or workflow re-import on this populated stack.

The ignored `.env` owns `COMPOSE_PROJECT_NAME`, `POSTGRES_PORT`, `N8N_PORT`, `LOCALSTACK_PORT`, database names and passwords, n8n encryption/signing keys, and notification controls. Keep its existing values and do not copy it into another checkout. The frontend uses its built-in default `http://127.0.0.1:8000` because `apps/web/.env.local` is absent; `NEXT_PUBLIC_UPLOAD_API_URL` can override that in a fresh checkout. Compose's internal helper resolves `postgres` on the canonical network. For the preserved SES environment, retain `NOTIFICATION_TRANSPORT=mock`, `NOTIFICATION_SES_ENABLED=0`, `NOTIFICATION_SES_MAX_ATTEMPTS=0`, and empty `NOTIFICATION_SES_AUTHORIZED_*` values. Keep the notification dispatcher stopped. Do not reset or retry either ambiguous notification.

AWS SES remains unverified: the prior controlled attempt returned `Forbidden`, no provider Message ID was returned, no inbox receipt was confirmed, and effective IAM authorization has not been independently verified. The Gemini adapter and structured validation have isolated tests, but no live Gemini API call succeeded and the local API key is absent. See [release verification](release-verification.md) and [submission summary](submission-summary.md).
