import { expect, test } from "@playwright/test";
import { readableError, STATUS_LABEL, TERMINAL_STATUSES, validateFile } from "../lib/contracts";
import { fileFingerprint } from "../lib/upload";

test("file validation checks extension, emptiness, and size", () => {
  expect(validateFile({ name: "users.csv", size: 200 }, 1_000)).toBeNull();
  expect(validateFile({ name: "users.txt", size: 200 }, 1_000)).toContain(".csv");
  expect(validateFile({ name: "users.csv", size: 0 }, 1_000)).toContain("empty");
  expect(validateFile({ name: "users.csv", size: 1_001 }, 1_000)).toContain("exceeds");
  expect(validateFile({ name: "../users.csv", size: 200 }, 1_000)).toContain(".csv");
});

test("all backend states have labels; terminal polling policy is explicit", () => {
  expect(STATUS_LABEL.processed_with_errors).toBe("Partially complete");
  expect(STATUS_LABEL.matching).toBe("Checking eligibility");
  expect(TERMINAL_STATUSES.has("uploaded")).toBe(false);
  expect(TERMINAL_STATUSES.has("matched")).toBe(true);
});

test("row validation codes map to safe field reasons", () => {
  expect(readableError("invalid_email").field).toBe("email");
  expect(readableError("duplicate_user_id").reason).toContain("already appeared");
  expect(readableError("new_code").reason).toBe("new code");
});

test("retry identity changes when equal-size CSV bytes change", async () => {
  const first = new File(["one"], "same.csv", { lastModified: 123 });
  const second = new File(["two"], "same.csv", { lastModified: 123 });
  expect(first.size).toBe(second.size);
  expect(await fileFingerprint(first)).not.toBe(await fileFingerprint(second));
});
