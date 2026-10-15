# Sanitized local M5 evidence — 2026-10-15

Workflow B JSON imported successfully into the running self-hosted n8n 2.43.5 instance and was published under `loanMatchingM5`. The real local E2E invoked its production webhook through the signed dispatcher. No bank rules were fabricated and no emails were sent.

| Observation | Result |
|---|---|
| Final demo upload batch | `46cd88dc-657c-47d9-9088-f0aafcc59f3f`; four deliberately synthetic CSV rows uploaded through FastAPI presigned POST and processed by the existing S3-event worker. |
| Matching execution | `8baeba9a-31cb-4019-9a91-41dd3a72cb4c`; n8n webhook accepted a signed committed outbox event. |
| Filter funnel | Four users × four current products in the development database (two official review-required, two synthetic current versions); SQL returned one candidate after verified/current, demo, age, score, employment, and currency gates. |
| Decision and persistence | One `ELIGIBLE_POTENTIAL` synthetic match inserted; zero official-bank matches. The other synthetic INR-income product was excluded because the uploaded user currency was unknown. |
| Completion and replay | Exactly one `matching.completed.v1` event for the batch. Replaying the same signed webhook returned `complete` and inserted no second match/event. |
| Gemini | Zero calls; no key configured, and the synthetic result was fully deterministic. |

An earlier E2E attempt failed because the dispatcher selected an older pending M3 event; the harness was corrected to claim its own event ID. A later attempt immediately after restarting the helper received a retryable failure while the helper was still starting; `make up` waited for health and the subsequent run passed. Docker's build cache also briefly exhausted its local VM; removing regenerable build cache and disabling uv cache in the image resolved it, and a final `docker compose build discovery` passed. These are real recovery observations, not hidden fixture results.

The benchmark is independently reproducible with `make matching-benchmark` and uses the assignment's live-download 10,000-row sample but synthetic, explicitly labelled rules. It does not persist or log the sample's email values. See [matching-benchmark.md](matching-benchmark.md) for measured results and limitations.
