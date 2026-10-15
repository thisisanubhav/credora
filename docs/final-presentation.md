# Reviewer presentation notes

## Thesis

The take-home emphasizes engineering judgment: a direct-to-object-storage CSV upload avoids API body limits; one PostgreSQL transaction commits users and an outbox event; n8n orchestrates discovery, matching and notification stages; SQL and deterministic rules avoid 500,000 LLM-per-pair requests. Unresolved financial facts stay unresolved. The zero-budget submission demonstrates these boundaries locally and includes a future AWS template, **not** a deployed cloud stack or a delivered SES email.

## Three decisions to defend

1. **Fail closed on lender criteria.** SBI and Axis provide partial/conditional public information. Their saved versions have official URLs and evidence but `review_required`, so the sample CSV cannot be used to claim eligibility. Positive match demos are opt-in synthetic only.
2. **Use n8n for orchestration, not as a data warehouse.** Schedule, webhooks, branching, paged candidate checks, persistence and summary are visible in A/B/C. Bounded Python helpers handle parsing/transactions and are independently tested. SQL eliminates hard failures before any advisory LLM call.
3. **Prefer reliable handoff over direct callbacks.** The transactional outbox survives n8n downtime. Signed, replay-fenced webhooks and uniqueness constraints tolerate at-least-once delivery. SES acceptance would still not prove inbox delivery or exactly-once sending.

## Numbers to say precisely

- Source CSV: 10,000 rows, measured parser/insert transaction 0.615 s on one local run, peak process RSS 97,812,480 bytes.
- Matching fixture: 50 **synthetic** products × 10,000 users = 500,000 theoretical comparisons; SQL yielded 100,499 candidate evaluations, a 79.9% reduction. Matching SQL/evaluator took 8.058 s, peak process RSS 117,489,664 bytes. LLM calls: zero. This run omitted match persistence and n8n overhead at scale.
- Fresh clone real browser batch: 3 accepted users, 3 synthetic matches, 2 `mocked` notifications, B/C n8n executions 34/35 terminal success. No SES ID or inbox receipt exists.

## Questions likely to arise

**Why not LLM per pair?** Simple numeric and category rules are deterministic. Unknown or qualitative source text may be extracted with structured Gemini only when authorized and source-grounded; an LLM never overrides hard failures.

**Is this AWS-ready?** The Python Lambda handlers and Serverless template were packaged/validated offline. The frontend still needs OIDC, private n8n/RDS hosting and verified TLS/SES setup. No cloud integration was exercised under ₹0.

**Why no real bank match?** Missing unconditional criteria and the sample CSV's unspecified income currency make a positive result unsafe. Showing a synthetic fixture separately is more honest than inventing a bank threshold.

**What is incomplete against the PDF?** Live RDS/SES, a received email, a recorded 5–10 minute video and form submission. Local deployment itself is allowed by the PDF, but the SES receipt remains mandatory and unfulfilled.
