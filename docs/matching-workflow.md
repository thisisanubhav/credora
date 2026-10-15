# Workflow B and outbox handoff

`workflows/matching.json` is the importable n8n Workflow B. Its Webhook Trigger is `/webhook/loan-matching`, followed by named HTTP stages to a private, testable helper in the existing Compose `discovery` service. This reuses one local helper image rather than adding a separate microservice. n8n owns the stage order, conditional replay branch, keyset-page loop, optional advisory step, match persistence, and completion. The helper implements bounded parameterized PostgreSQL operations and pure deterministic rules; no single endpoint performs the whole workflow.

## Local operation

```sh
python3 scripts/local_env.py extend-m5  # Once for an existing ignored .env
make up
make db-upgrade
make db-role
make matching-import
docker compose --project-directory . --env-file .env -f infrastructure/docker-compose.yml exec -T n8n n8n publish:workflow --id=loanMatchingM5
docker compose --project-directory . --env-file .env -f infrastructure/docker-compose.yml restart n8n
uv run --frozen --env-file .env python -m scripts.seed_matching_demo
make matching-e2e
```

Import alone does not publish the webhook. The CLI publication is a local operator action; restarting n8n registers it. `make matching-dispatch` sends one due ready event; the E2E command selects only its own event to avoid consuming unrelated older outbox rows. The matching helper's source directories are bind-mounted read-only in Compose so local development sees current code even when the image cache is constrained; production builds still bake code into the image. There is no public helper port. Do not enable the demo flag or HTTP webhook outside localhost.

## Node sequence

1. **Signed Matching Webhook** accepts only POST.
2. **Authenticate and Claim Event** forwards parsed body and headers to the helper. It verifies HMAC-SHA256 over `timestamp + '.' + canonical sorted JSON body`, checks a ±5-minute timestamp window, validates the event schema and ID header, and claims the event in PostgreSQL. No secret appears in n8n JSON. Unlike the earlier architecture's raw-body signature proposal, canonical JSON is used because n8n supplies a parsed body to its HTTP node; both sender and verifier use the same explicit canonicalization.
3. **New or Resumable Event?** branches on the unique execution claim. **Acknowledge Durable Claim** or **Acknowledge Duplicate** returns HTTP 202 only after the claim transaction commits. The dispatcher checks this acknowledgement before marking the outbox delivered.
4. **Load Batch Metadata** reads batch-scoped counts and demo mode, never emails.
5. **SQL Candidate Prefilter** executes the parameterized SQL in `services/eligibility/sql/prefilter.sql` for 20 user IDs per keyset page (at most 1,000 pairs with 50 products). It excludes hard failures, unverified/retired products, and synthetic products for ordinary batches. It does not load the Cartesian product into n8n.
6. **Deterministic Rule Evaluation** checks the full versioned `all`/`any` document using decimal comparisons and produces structured decisions and reason codes.
7. **Selective Gemini Advisory** runs only for `REVIEW_REQUIRED` cases, behind a five-call transactional budget. It never promotes a case to eligible; without a key it is a no-op marked `unavailable`.
8. **Persist Potential Matches** inserts only potential decisions with `ON CONFLICT DO NOTHING`. A page receipt in the locked execution metrics makes retries/replays idempotent and advances the cursor. **More Candidate Pages?** loops while a next cursor exists.
9. **Commit Completion Event** atomically marks the batch/execution succeeded and inserts one stable `matching.completed.v1` outbox event for Workflow C in M6. **Execution Summary** returns only counts and IDs.

## Delivery and recovery

The dispatcher claims due `upload_batch.ready.v1` events with `FOR UPDATE SKIP LOCKED`, a 90-second lease, and a fencing comparison on completion. It sends only event and batch UUIDs plus an HMAC signature. It retries transport/429/5xx failures with capped exponential backoff and jitter; schema/auth 4xx failures are quarantined. It records attempts in `retry_count` and stable error codes, never payload bodies. Delivery is **at least once**, not exactly once. If it crashes after n8n's durable claim but before recording 202, the lease expires and the same event is resent; the unique `workflow_executions.event_id`, page receipts, and unique match key absorb replay. A stale running execution may be resumed after 15 minutes without heartbeat.

The webhook is acknowledged after the claim, before all matching pages complete. If n8n dies later, the outbox may already be `delivered`; the dispatcher watch loop requeues a run with no heartbeat for 15 minutes. A slow run that stops updating its heartbeat for longer than that could be concurrently retried; page receipts and the match unique key protect data, but operators should tune the lease after load testing. The local E2E exercises successful completion and duplicate delivery; fixture tests exercise stale requeue. The helper trusts the private Compose network after webhook verification; deployment needs TLS, least-privilege service authentication, and network isolation.
