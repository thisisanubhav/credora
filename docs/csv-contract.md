# CSV ingestion contract (M3)

The [assignment sample](https://drive.google.com/file/d/1KBaZRkfr7T2kVBKSr_2fr7v2tTe6f8qu/view?usp=sharing) was inspected on 2026-10-15. It is UTF-8 without BOM, uses CRLF, and contains 10,000 data rows (993,191 bytes). Its exact header is `user_id,name,email,monthly_income,credit_score,employment_status,age`. The `name` column is not required by the assignment or database and is deliberately ignored to avoid storing unnecessary personal data. The six other columns are mandatory; their order can vary. Other columns, repeated headers, missing headers, an empty file, or a header-only file cause whole-file rejection.

Observed sample values: `user_id` is a nonnumeric string; `monthly_income` uses whole-number strings from 25000 to 150000; `credit_score` is integer 650–800; `age` is integer 22–50. No cells are missing, and there are no duplicate user IDs. Emails repeat across rows (7,368 duplicates), so email is **not** a key. Employment values are `Salaried` (3,389), `Self-Employed` (3,371), and `Business` (3,240). No currency or missing-value marker is specified. We therefore store `income_currency = NULL`, not an invented denomination; matching to currency-specific income rules must fail closed until a currency is established.

M3 accepts UTF-8 (optional BOM), RFC-style quoted CSV, a single header, and no more than the configured byte limit (default 10 MB). Files are streamed; the CSV parser is strict. Empty physical CSV records count as rejected rows. A malformed quoted record, invalid UTF-8, invalid headers, or oversized object rejects the **whole file** and rolls back user inserts. An individual row with an incorrect column count or invalid field is rejected while valid rows proceed. `upload_row_errors` preserves every rejected row number and safe error codes, **not** raw row values or email addresses. The batch summary returns the first 100 examples, and `GET /uploads/{batch_id}/errors?offset=0&limit=100` pages through all errors. Total accepted and rejected counts remain exact. Users repair the original CSV and upload again; raw invalid rows are not copied to a second PII store.

| Column | Rule |
|---|---|
| `user_id` | Trimmed nonempty string, at most 128 characters; unique inside one batch. The first valid occurrence wins; later duplicates are rejected. Across batches the same external ID is permitted. |
| `email` | Syntactically validated, normalized lowercase address, maximum 320 characters. No deliverability check or email send in M3. |
| `monthly_income` | Nonnegative finite decimal, at most 12 integer digits and 2 decimal places; stored as `NUMERIC(14,2)`. No assumed currency. |
| `credit_score` | Decimal digits only, integer 0–1000, matching the existing M2 database constraint. |
| `age` | Decimal digits only, integer 0–130, matching the existing M2 database constraint. |
| `employment_status` | Trimmed nonempty source text, at most 128 characters. Preserve as `employment_status_raw`; normalize known `Salaried` and `Self-Employed` forms to `salaried` and `self_employed`. `Business` and all other nonempty labels map to `other`, which is **not** automatic eligibility. M5 must use source-specific evidence before qualifying them. |
| `name` | Optional, ignored. |

The assignment does not define currency, credit-scoring system, age minimum, or employment taxonomy. M3 applies only the M2 storage constraints and deterministic syntax/range validation; stricter loan rules belong to matching. Rows are not cleaned with an LLM.

Each upload requires an `Idempotency-Key` and declared filename, `text/csv` (or `application/csv`) content type, and byte size. The API rejects declared oversize files; the presigned POST policy and worker independently enforce the configured ceiling. Since presigned policies cannot ensure the uploaded bytes match the caller's declared size, the worker trusts only S3's actual object length. It also validates the event bucket/key against a known batch and compares ETags.
