# Gemini live validation — 2026-10-17

## Latest attempt — HTTP 200; full harness validation PARTIAL

On 2026-10-17 at 11:01:23 UTC, a separately authorized single request used the corrected `APPLICATION_JSON` enum and model `gemini-3.8-flash`. Provider response: **HTTP 200**, model version `gemini-3.8-flash`; usage: **96 prompt tokens, 106 candidate tokens, 377 thought tokens, 579 total tokens**. Exactly one request occurred, with synthetic qualitative text only and a transport guard blocking any second request. No workflow, database write, SES send or helper restart was performed.

**Actual LLM API use: PASS.** The adapter returned successfully, which means its strict clause schema and exact source-quote checks passed. This is established by the harness control flow: the subsequent `validate_candidate` raised an ordinary `ValueError`; adapter validation failures would instead have raised `GeminiError`. The returned clauses were not retained by the harness, so their count/content cannot be independently re-inspected from saved evidence.

**Complete candidate persistence validation: PARTIAL.** The harness hashed the synthetic text alone rather than text plus newline plus interest-rate text. Offline reconstruction independently reproduced `page_evidence_hash_mismatch`; correcting the fixture's hash made the deterministic candidate pass validation. This was a harness defect, not a rejected Gemini response. The live returned candidate was not retained, so a complete revalidation of that specific candidate was not performed. No database persistence or successful n8n Gemini-stage execution is claimed.

Billing-disabled Free Tier remains owner-confirmed. Provider `serviceTier=standard` is not independent proof of billing tier or zero cost. No second request was made. The earlier rejection below is historical. A future full workflow integration demonstration should use correctly hashed evidence and retain sanitized validation results.


## Outcome: rejected request; offline repair verified

At 10:59:23 UTC, one owner-authorized request invoked the discovery adapter against `gemini-3.8-flash`. Only explicitly synthetic qualitative text was transmitted; no applicant rows, email addresses, financial records or credentials were recorded in evidence. No database records were written and no n8n workflow was triggered. The owner had confirmed Free Tier with billing disabled; billing was not independently inspected.

A private harness wrapped HTTPX with a one-request transport guard, no transport retries and no redirects. It recorded the first attempt before sending; any subsequent adapter retry would be blocked before reaching the network. Exactly **one** HTTP request occurred.

- HTTP status: **400**.
- Provider status: **INVALID_ARGUMENT**.
- Rejected field: `generation_config.response_format.text.mime_type`.
- Rejected value: `application/json`.
- Adapter result: `api_rejected`; no successful extraction or token usage returned.

## Confirmed cause and correction

The [official generateContent REST reference](https://ai.google.dev/api/generate-content#TextResponseFormat) defines `TextResponseFormat.mimeType` as an enum, whose JSON value for structured output is `APPLICATION_JSON`. The adapters incorrectly used the media-type string accepted by different API/SDK shapes. This is a request-contract defect, not evidence of an invalid API key, unavailable model or exhausted quota; those checks remain unverified.

The smallest correction changes only the enum value in both `services/discovery/gemini.py` and `services/eligibility/gemini.py`. Existing schema, evidence verification, fail-closed matching, recipient controls and retry behavior are unchanged. New mocked wire-contract tests cover both adapters and ensure qualitative advice cannot promote a review-required decision.

## Fresh verification

- Discovery and matching suites: **38 passed**, one existing Starlette/httpx deprecation warning.
- Ruff: PASS.
- Mypy: PASS, 54 source files.
- SES remains mock/disabled/zero attempts; latest Workflow C remains **185**.
- No second Gemini request, SES call, workflow execution or helper restart was performed.

## Next step

A separately authorized single request must validate the corrected adapter against the real API. The running helper was not restarted to load the corrected Python modules. Its service mounts the source read-only, but loaded Python code is not assumed to refresh automatically. Refresh only the helper before a future workflow integration test, preserving the patched n8n image override and mock SES settings.

**Actual successful LLM usage remains NOT_VERIFIED.** Offline test success does not satisfy the assignment's live LLM-use requirement. No changes were pushed by this verification task.
