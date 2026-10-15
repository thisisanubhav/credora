export type BatchStatus =
  | "uploaded" | "processing" | "processed" | "processed_with_errors"
  | "rejected" | "failed" | "matching" | "matched" | "match_failed";

export type PresignResponse = {
  batch_id: string;
  upload: { url: string; fields: Record<string, string> };
  expires_in: number;
};

export type BatchResponse = {
  batch_id: string;
  status: BatchStatus;
  total_rows: number;
  accepted_rows: number;
  rejected_rows: number;
  errors: Record<string, unknown>;
};

export type RowError = { row: number; codes: string[] };
export type ErrorsResponse = { batch_id: string; errors: RowError[]; offset: number; limit: number };

export const TERMINAL_STATUSES: ReadonlySet<BatchStatus> = new Set([
  "processed", "processed_with_errors", "rejected", "failed", "matched", "match_failed",
]);

export const STATUS_LABEL: Record<BatchStatus, string> = {
  uploaded: "Awaiting processing",
  processing: "Validating CSV",
  processed: "Ingestion complete",
  processed_with_errors: "Partially complete",
  rejected: "File rejected",
  failed: "Processing failed",
  matching: "Checking eligibility",
  matched: "Processing complete",
  match_failed: "Eligibility workflow failed",
};

export const ROW_ERROR: Record<string, { field: string; reason: string }> = {
  invalid_user_id: { field: "user_id", reason: "A user ID is required (maximum 128 characters)." },
  duplicate_user_id: { field: "user_id", reason: "This user ID already appeared in this upload." },
  invalid_email: { field: "email", reason: "Enter a valid email address." },
  invalid_monthly_income: { field: "monthly_income", reason: "Use a non-negative amount with at most two decimal places." },
  invalid_credit_score: { field: "credit_score", reason: "Use a whole number from 0 to 1000." },
  invalid_age: { field: "age", reason: "Use a whole number from 0 to 130." },
  invalid_employment_status: { field: "employment_status", reason: "An employment value is required." },
  invalid_column_count: { field: "row", reason: "The row has the wrong number of columns." },
  empty_row: { field: "row", reason: "The row is empty." },
};

export function validateFile(file: Pick<File, "name" | "size">, maximum: number): string | null {
  if (!/^[^/\\\x00-\x1f]+\.csv$/i.test(file.name)) return "Choose a file ending in .csv.";
  if (file.size === 0) return "The CSV is empty. Choose a file with a header and data rows.";
  if (file.size > maximum) return `The CSV exceeds the ${Math.round(maximum / 1_000_000)} MB upload limit.`;
  return null;
}

export function readableError(code: string): { field: string; reason: string } {
  return ROW_ERROR[code] ?? { field: "row", reason: code.replaceAll("_", " ") };
}
