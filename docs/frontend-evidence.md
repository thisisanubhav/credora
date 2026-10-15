# M7 frontend evidence and limitations

## Scope and contracts

The browser is a thin client over M3: `POST /uploads` returns `{batch_id,upload:{url,fields},expires_in}`; `GET /uploads/{batch_id}` returns the actual status and row counts; `GET /uploads/{batch_id}/errors?offset=&limit=` returns row numbers and validation codes. Client-side extension/size checks are advisory; the API, presigned POST, and worker enforce their own limits. The page does not request match or notification data. A batch ID in the URL restores status on reload. Processing duration is not in the API contract and is not estimated.

## Actual local browser execution (2026-10-15)

With PostgreSQL, n8n, and LocalStack running, `make api`, `make local-worker`, and `make web-dev` were started from this checkout. A visible browser at `127.0.0.1:3107` created files using synthetic test identifiers, requested a real presigned policy from FastAPI, and submitted the multipart POST directly to LocalStack. The bridge detected the object and called the existing ingestion handler. No AWS/SES calls occurred.

| Batch | Browser/API outcome | PostgreSQL/outbox check |
|---|---|---|
| `4bff832d-8641-4acf-ba18-edf8633ecd89` | `processed_with_errors`; total 2, accepted 1, rejected 1; row 3 `invalid_email` from paged errors endpoint | ORM count: 1 user; 1 `upload_batch.ready.v1` outbox event |
| `87e02539-4534-473d-ab91-8b0b41fc7425` | `processed`; total 1, accepted 1, rejected 0 | API status and visible browser summary verified; database count not separately queried |

An additional all-invalid synthetic browser upload was rejected (batch `70208f71-466a-4fd5-87f9-4ebde1105636`) because `.invalid` is not accepted as an applicant email. It was not used as evidence of success.

[Real completion screenshot](../artifacts/m7/real-localstack-complete.png) · [Real partial/error screenshot](../artifacts/m7/real-localstack-errors.png)

The following screenshots are **Playwright mocked-state evidence**, not claims of separate real uploads: [initial desktop](../artifacts/m7/initial-desktop.png), [initial mobile](../artifacts/m7/initial-mobile.png), [in-flight transfer](../artifacts/m7/upload-progress.png), [completed state](../artifacts/m7/processing-complete.png), [row-level validation](../artifacts/m7/validation-errors.png). Generate them with `cd apps/web && npx playwright test tests/evidence.spec.ts`. Next.js development tooling is hidden only in those screenshots; application elements are unchanged.

## Verification and safety notes

The Playwright UI tests use mocked API/S3 responses to exercise deterministic failure, polling, pagination, and retry states. They do not substitute for the real browser-to-LocalStack run above. The API, bucket, and frontend bind to loopback; FastAPI and LocalStack CORS allow only the configured browser origin. No CSV bytes, sample addresses, or credentials are included in screenshots. A signed S3 policy is a bearer capability until expiry and must not be logged or retained beyond the upload. `sessionStorage` contains only an idempotency key and file fingerprint, not file contents. CORS is not authentication. The anonymous local upload API must not be published without authentication, rate limits, and abuse controls.

The UI stops automatic polling at ingestion completion because matching can proceed asynchronously; manual refresh can show later `matching`/`matched` states. The local S3 event bridge is polling-based and designed for small local demos, not production-scale event delivery. Native S3 notifications remain the production path. Browser screenshots and API status do not prove SES delivery; M6 remains mock-only by default.
