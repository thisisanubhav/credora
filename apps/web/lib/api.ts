import type { BatchResponse, ErrorsResponse, PresignResponse } from "./contracts";

export const API_URL = process.env.NEXT_PUBLIC_UPLOAD_API_URL ?? "http://127.0.0.1:8000";

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

async function jsonRequest<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      ...init,
      cache: "no-store",
      signal: init?.signal ?? AbortSignal.timeout(10_000),
    });
  } catch {
    throw new ApiError(0, "Cannot reach the upload service. Check that the local API is running, then retry.");
  }
  if (!response.ok) {
    let detail = "The request could not be completed.";
    try {
      const body = await response.json() as { detail?: string };
      if (typeof body.detail === "string") detail = body.detail;
    } catch { /* Keep a safe generic message. */ }
    throw new ApiError(response.status, detail);
  }
  return response.json() as Promise<T>;
}

export function requestUpload(file: File, idempotencyKey: string): Promise<PresignResponse> {
  return jsonRequest<PresignResponse>("/uploads", {
    method: "POST",
    headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey },
    body: JSON.stringify({ filename: file.name, size_bytes: file.size, content_type: "text/csv" }),
  });
}

export function fetchBatch(batchId: string): Promise<BatchResponse> {
  return jsonRequest<BatchResponse>(`/uploads/${encodeURIComponent(batchId)}`);
}

export function fetchErrors(batchId: string, offset: number, limit = 20): Promise<ErrorsResponse> {
  return jsonRequest<ErrorsResponse>(`/uploads/${encodeURIComponent(batchId)}/errors?offset=${offset}&limit=${limit}`);
}
