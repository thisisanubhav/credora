# M9 local security audit

Scope: repository code, three n8n exports, Compose, Serverless template, runtime PostgreSQL role, browser UI, and safe local adversarial tests on 2026-10-15. No third-party site was attacked, AWS was not contacted, and no SES mail was sent. **PASS** means a local control/test passed, not a production penetration-test claim.

| Control | Finding / evidence | Status |
|---|---|---|
| JWT verification and batch ownership | AWS HTTP API routes declare JWT authorizer; Mangum test supplies API Gateway-verified `sub`, and other subject gets 404 for status/errors. Missing subject gets 401. Live issuer/JWKS behavior untested. | PARTIAL |
| HMAC and replay | Signed `event_id`/timestamp/body, constant-time comparison, five-minute window, durable execution claim; tests and real duplicate completion replay created no new notifications. | PASS locally |
| Request validation | Metadata, byte limits, headers, UTF-8, row fields, S3 key/ETag and schema constraints tested. Local API has no public authentication/rate limit. | PARTIAL |
| SQL injection | SQLAlchemy binds parameters; user/source data are not interpolated into query text. Representative source and batch tests passed. | PASS locally |
| SSRF | Discovery only accepts two compiled HTTPS official URLs; checks public DNS, robots, redirects, response size/timeouts. DNS can change between preflight resolution and the HTTP client's later lookup, so DNS-rebinding pinning remains open. | PARTIAL |
| XSS / HTML | Notification template escapes names/rates/URLs and requires HTTPS; React text rendering escapes API data. Unit tests cover escaping. | PASS locally |
| CSV formula injection | CSV values are parsed into typed fields and never exported to a spreadsheet or rendered as formulas. No current formula-execution sink; future CSV export must escape spreadsheet metacharacters. | PASS for current flow |
| Sensitive logging / secrets | Ingestion suppresses row/DB values in unexpected-error logs; tests check no sensitive values. `.env`, AWS env and key patterns are gitignored; tracked-file scan found no key pattern. | PASS locally |
| CORS / upload size | Exact browser origin, short-lived presigned POST and independent worker byte ceiling. CORS is not authentication. Real LocalStack bucket CORS needed reinitialization after daemon restart. | PARTIAL |
| Internal service authentication | Helper HTTP endpoints are not individually authenticated; they rely on unpublished Docker networking. A peer on the Compose network could call discovery/matching/notification steps directly. This is a **deployment blocker**: provide a private authenticated service channel before any shared/cloud host. | FAIL for hostile shared network |
| Least-privilege database / IAM | Runtime DB role cannot DDL/DELETE or alter historical eligibility rules. API/worker IAM definitions separate scoped S3 actions, but effective IAM was not tested on AWS. | PARTIAL |
| Synthetic isolation | Only explicitly flagged local batches see synthetic sources. M9 adds an API-side AWS-mode denial even if `ALLOW_SYNTHETIC_DEMO=1`. Real bank versions remain review-required/unmatchable. | PASS locally |
| Recipient isolation | CSV addresses are absent from notification queries; mock-only mode is default and SES requires explicit switches and verified test identities. Real browser batch yielded two `mocked` rows, zero SES IDs. | PASS locally; live SES BLOCKED_BY_ZERO_BUDGET |
| Dependencies | `pip-audit` on locked production Python requirements found zero known vulnerabilities; frontend production-only `npm audit` found zero. Full frontend audit has five high findings inherited from unpatched dev-only `braces@3.0.3` after PostCSS repair. Infrastructure npm audit found zero. | PARTIAL |

## Highest unresolved risks

1. **P1 internal helper trust boundary:** network isolation is not a substitute for endpoint authentication on a future multi-tenant/shared host. Avoid exposing port 8001. Design a credential-backed n8n→helper channel and test it before deployment; no speculative header secret was added to workflow exports in M9.
2. **P1 cloud identity gap:** the M7 browser cannot acquire OIDC tokens for the AWS JWT API. Do not remove authorization to make the UI work. No live JWKS, ownership, throttling or RDS TLS verification was performed.
3. **P2 n8n/PostgreSQL compatibility:** installed n8n 2.43.5 warns that PostgreSQL 16 receives compatibility support only; the assignment/M1 pin is PostgreSQL 16. Current local workflows run, but an upgrade plan and compatibility test are needed before a long-lived service.
4. **P1 execution-state mismatch:** n8n's webhook execution rows for B/C remain `running` after app-side completion. This is a reliability and audit-trail concern; verify terminal execution state before any production use. Do not infer success from the helper database alone.
4. **P2 dependency advisory:** [braces GHSA-vfj7-8cjw-p6xm](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm) has no published patched version at audit time; the affected path is development lint tooling, not the deployed frontend production dependency tree. Track upstream rather than suppress the finding.
5. **P2 RDS transport:** `sslmode=require` encrypts but does not verify the RDS certificate/hostname. `verify-full` plus CA bundle is required before public AWS operation.

No vulnerability scan guarantees the absence of vulnerabilities. The zero-budget policy makes all live AWS/SES controls **BLOCKED_BY_ZERO_BUDGET**.
