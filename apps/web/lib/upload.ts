import type { PresignResponse } from "./contracts";

export class StorageError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

export function uploadToStorage(file: File, policy: PresignResponse["upload"], onProgress: (percent: number) => void): Promise<void> {
  return new Promise((resolve, reject) => {
    let url: URL;
    try {
      url = new URL(policy.url);
      if (url.protocol !== "https:" && !(url.protocol === "http:" && ["localhost", "127.0.0.1"].includes(url.hostname))) {
        throw new Error("Unsafe upload URL");
      }
    } catch {
      reject(new StorageError(0, "The storage upload address is invalid."));
      return;
    }
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url.toString());
    xhr.timeout = 120_000;
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && event.total > 0) onProgress(Math.min(100, Math.round(event.loaded * 100 / event.total)));
    };
    xhr.onerror = () => reject(new StorageError(0, "Storage is unavailable or the browser blocked the upload. Check local S3/CORS and retry."));
    xhr.ontimeout = () => reject(new StorageError(0, "The upload timed out. Check your connection and retry."));
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) { onProgress(100); resolve(); }
      else if (xhr.status === 403) reject(new StorageError(403, "The upload permission expired or was denied. Retry to request a fresh link."));
      else reject(new StorageError(xhr.status, `Storage rejected the upload (HTTP ${xhr.status}). Retry or check the file size.`));
    };
    const form = new FormData();
    for (const [key, value] of Object.entries(policy.fields)) form.append(key, value);
    form.append("file", file, file.name);
    xhr.send(form);
  });
}
