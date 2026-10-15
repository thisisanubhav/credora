# Sanitized M4 local execution evidence — 2026-10-15

The following records a live local n8n CLI execution against the two exact official HTTPS source URLs in `docs/loan-sources.md`. It is not derived from synthetic fixtures. No credentials, full source HTML, or user CSV data are included.

| Check | Observed result |
|---|---|
| n8n import | `Successfully imported 1 workflow.` for `workflows/discovery.json` |
| Manual n8n CLI execution | `Execution was successful`; triggered via `make discovery-run` (n8n Manual Trigger path) |
| Initial run | `fec5af5b-8cbd-441f-9c35-9413da55078d`; `succeeded`; SBI `created`, Axis `created` |
| Repeat run | `608f8316-114a-4387-ac5b-9a0f64e70a7f`; `succeeded`; SBI `unchanged`, Axis `unchanged` |
| Final post-import run | `7ac1bef1-abc6-4e9f-bb03-2332f8b7285a`; `succeeded`; SBI `unchanged`, Axis `unchanged`; n8n summary combined both source outcomes |
| PostgreSQL current product count | 2; total version-row count 2 after repeated live runs |
| SBI current version | v1, 10.0000% starting quote, INR indicated by source text, minimum age 21 years, `review_required` |
| Axis current version | v1, 9.9900% p.a. starting quote, INR indicated by source text, minimum age 21 years, `review_required` |
| Missing/conditional criteria | Minimum monthly income `UNKNOWN` on both; no automatic qualification |
| Gemini | No key configured; n8n path returned `llm_status: unavailable`; no paid call claimed |

The crawler also retrieved each source's `robots.txt` and found the target URL permitted on the verification date. No source page bytes are checked into the repository. This evidence is a timestamped snapshot, not a guarantee of continued page accessibility or unchanged interest rates. For the final video, open Workflow A and its execution summary in n8n, then query the current version rows and `workflow_executions` in PostgreSQL. The n8n owner UI was not used for the CLI run; the imported workflow can be opened in the self-hosted editor.

Operational caveat observed: n8n 2.43.5 logs that PostgreSQL 16 receives compatibility support only; the existing M1 PostgreSQL 16 choice works in this test but should be upgraded to a supported version before production. The n8n image also warns that its Python task runner is unavailable; Workflow A uses the JavaScript Code node and executed successfully.
