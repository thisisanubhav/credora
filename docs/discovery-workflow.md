# Workflow A: Loan Product Discovery

`workflows/discovery.json` is the importable self-hosted n8n workflow. It owns the schedule, per-source fan-out, Gemini branch, validation/persistence sequence, and execution summary. The internal `discovery` Compose service provides small testable HTTP steps; it is reachable only on the Compose network, has no published host port, and is not a substitute cron job. Importing leaves the schedule inactive until an operator activates it in n8n. The Schedule Trigger interval is 24 hours and may be edited in the n8n editor; Manual Trigger supports demonstrations.

## Run locally

From the repository root, with the existing ignored `.env` and Docker running:

```sh
uv sync --frozen
make up
make db-upgrade
make db-role
make discovery-import
make discovery-run
```

`make discovery-run` stops the editor container temporarily and uses n8n's CLI runner on the same Compose network, then restarts the editor even if execution fails. This avoids the editor's task-broker port collision with the CLI runner. Alternatively, click **Manual Trigger** in the n8n editor at `http://localhost:5678`. Activate the workflow there only if daily live crawling is desired. Inspect runs with `make status` and the n8n executions view; query `workflow_executions`, `product_sources`, and `loan_products` through the local PostgreSQL connection described in the README. Do not expose the discovery service publicly or send arbitrary URLs to it.

## Nodes and contract

1. **Manual Trigger / Daily Schedule**: initiate the run.
2. **Start Discovery Run**: create a `workflow_executions` record and return the two configured source keys.
3. **Source Configuration**: fan out one n8n item per allowlisted source; no user-supplied URLs.
4. **Fetch Official Source**: retrieve robots and HTML with 15-second timeout, bounded retries, 1.5 MB HTML cap, disabled redirects, and a one-second source delay; return a bounded source excerpt, retrieval time, and SHA-256.
5. **Extract Deterministic Criteria**: parse source-supported rate and minimum age; preserve conditional prose as ambiguous and unknown. Never infer a universal threshold from a branch-specific threshold.
6. **Needs Gemini? / Gemini Qualitative Extraction**: call the adapter only when ambiguous text exists. A missing key returns `unavailable` and preserves deterministic output. `GEMINI_MODEL` defaults to `gemini-3.8-flash`, verified against [Google's model documentation](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash); the API uses [structured JSON output](https://ai.google.dev/gemini-api/docs/structured-output). `GEMINI_API_KEY` is read only from the ignored environment, never embedded in the export. No live Gemini call was made in M4 because no key was configured.
7. **Validate Source Evidence**: Pydantic and deterministic checks require exact allowlisted source identity, matching text hash, quoted evidence, numeric values present in their quotes, and explicit criterion states. `KNOWN`, `UNKNOWN`, `NOT_APPLICABLE` are distinct; absent criteria cannot be treated as passing. An LLM never independently declares eligibility.
8. **Persist Product Version**: source-row lock plus partial unique current-version index serialize concurrent updates. Identical meaningful data refreshes `last_seen_at`; a change inserts a new immutable version and demotes the prior one. A less trustworthy `review_required` extraction cannot overwrite an existing `verified` current version.
9. **Record Source Outcome / Execution Summary**: classify per-source `created`, `versioned`, `unchanged`, `preserved_verified`, or `failed`; compute run status `succeeded`, `partial`, or `failed` after all sources report. n8n retains the execution, while PostgreSQL stores compact source outcomes.

Source pages may change between retrievals. The extractor deliberately fails closed when its section markers disappear or the excerpt becomes too large. Numeric income, score, employment mapping, and age-at-maturity are **not** inferred from ambiguous prose. Existing M2 `eligibility_rules` JSONB stores grounded quotes; M4 adds nullable `currency_code` and explicit `criterion_states` JSONB via Alembic revision `5f16aa35b814`. The migration is an additive schema clarification, not a table redesign. `review_required` products are not matchable in M5 without separate validated evidence and currency compatibility.

## Recovery and limits

Per-source HTTP/parse/validation failures return a safe error code and continue to outcome recording. A n8n infrastructure failure between starting and recording may leave a `running` execution, which an operator must inspect and mark/re-run; automatic stale-run reconciliation is not implemented. The n8n HTTP nodes do not contain their own retry loop; the fetcher and Gemini adapter have bounded retries. A failed persistence call can stop that execution without marking later sources; it does not corrupt existing products. Future hardening should add an n8n error workflow and stale-run sweeper before unattended operation. The internal step API currently trusts members of the local Compose network; public deployment requires service authentication and network isolation.

The two live pages supply **partial**, not complete, eligibility. Both live M4 records are `review_required`. Successful crawling is not evidence of automatic qualification. The exact words and rates can change, so use the queryable stored version and source URL rather than copying a past marketing claim into an eligibility rule.
