import { expect, test, type Page } from "@playwright/test";

const API = "http://127.0.0.1:8000";
const STORAGE = "http://127.0.0.1:4566/loan-engine-local";
const CSV = "user_id,email,monthly_income,credit_score,employment_status,age\none,one@example.com,50000,710,Salaried,30\n";

async function choose(page: Page, name = "users.csv", content = CSV) {
  await page.locator("#csv-file").setInputFiles({ name, mimeType: "text/csv", buffer: Buffer.from(content) });
}

async function mockPresign(page: Page) {
  let calls = 0;
  const keys: string[] = [];
  await page.route(`${API}/uploads`, async (route) => {
    calls += 1;
    keys.push(route.request().headers()["idempotency-key"]);
    await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({
      batch_id: "11111111-1111-4111-8111-111111111111",
      expires_in: 600,
      upload: { url: STORAGE, fields: { key: "uploads/test/file.csv", "Content-Type": "text/csv", policy: "fake" } },
    }) });
  });
  return { count: () => calls, keys };
}

async function mockStatus(page: Page, statuses: string[], rejected = 0) {
  let calls = 0;
  await page.route(`${API}/uploads/11111111-1111-4111-8111-111111111111`, async (route) => {
    const status = statuses[Math.min(calls, statuses.length - 1)];
    calls += 1;
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
      batch_id: "11111111-1111-4111-8111-111111111111", status,
      total_rows: status === "uploaded" ? 0 : 3 + rejected,
      accepted_rows: status === "uploaded" ? 0 : 3,
      rejected_rows: status === "uploaded" ? 0 : rejected, errors: {},
    }) });
  });
  return () => calls;
}

test("initial page is accessible by keyboard and responsive", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Upload applicant data" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Upload CSV" })).toBeDisabled();
  await expect(page.locator("#csv-file")).toHaveAttribute("accept", /csv/);
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Credora home" })).toBeFocused();
  for (let index = 0; index < 5; index += 1) await page.keyboard.press("Tab");
  await expect(page.locator("#csv-file")).toBeFocused();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("heading", { name: "CSV format" })).toBeVisible();
  const width = await page.evaluate(() => document.documentElement.scrollWidth);
  expect(width).toBeLessThanOrEqual(390);
});

test("rejects invalid extension and oversized CSV before API call", async ({ page }) => {
  let calls = 0;
  await page.route(`${API}/uploads`, async (route) => { calls += 1; await route.abort(); });
  await page.goto("/");
  await choose(page, "users.txt");
  await expect(page.getByRole("alert").filter({ hasText: ".csv" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Retry upload" })).toBeEnabled();
  await choose(page, "large.csv", "x".repeat(10_000_001));
  await expect(page.getByRole("alert").filter({ hasText: "exceeds" })).toBeVisible();
  expect(calls).toBe(0);
});

test("direct POST, real progress, polling, and batch summary", async ({ page }) => {
  const presign = await mockPresign(page);
  const polls = await mockStatus(page, ["uploaded", "processing", "processed"]);
  let storageCalls = 0;
  await page.route(STORAGE, async (route) => {
    storageCalls += 1;
    const body = route.request().postData() ?? "";
    expect(body).toContain("user_id,email");
    await route.fulfill({ status: 204, body: "", headers: { "access-control-allow-origin": "http://127.0.0.1:3107" } });
  });
  await page.goto("/");
  await choose(page);
  await page.getByRole("button", { name: "Upload CSV" }).click();
  await expect(page.getByRole("progressbar", { name: "CSV upload progress" })).toHaveAttribute("aria-valuenow", "100");
  await expect(page.getByRole("status")).toContainText("Ingestion complete", { timeout: 15_000 });
  await expect(page.getByText("Batch ID:")).toBeVisible();
  await expect(page.getByText("3", { exact: true })).toHaveCount(2);
  expect(presign.count()).toBe(1);
  expect(storageCalls).toBe(1);
  expect(polls()).toBeGreaterThanOrEqual(3);
});

test("partial processing shows paged row errors without applicant values", async ({ page }) => {
  await mockPresign(page);
  await mockStatus(page, ["processed_with_errors"], 22);
  await page.route(STORAGE, (route) => route.fulfill({ status: 204, headers: { "access-control-allow-origin": "http://127.0.0.1:3107" } }));
  await page.route(`${API}/uploads/11111111-1111-4111-8111-111111111111/errors*`, async (route) => {
    const url = new URL(route.request().url());
    const offset = Number(url.searchParams.get("offset"));
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
      batch_id: "11111111-1111-4111-8111-111111111111", offset, limit: 20,
      errors: Array.from({ length: offset === 0 ? 20 : 2 }, (_, index) => ({ row: offset + index + 2, codes: ["invalid_email"] })),
    }) });
  });
  await page.goto("/");
  await choose(page);
  await page.getByRole("button", { name: "Upload CSV" }).click();
  await expect(page.getByRole("status")).toContainText("Partially complete");
  await expect(page.getByText("Rows 1–20 of 22")).toBeVisible();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.getByText("Rows 21–22 of 22")).toBeVisible();
  await expect(page.getByText("one@example.com")).toHaveCount(0);
});

test("expired upload permission retries with same idempotency key", async ({ page }) => {
  const presign = await mockPresign(page);
  let sends = 0;
  await page.route(STORAGE, (route) => {
    sends += 1;
    return route.fulfill({ status: sends === 1 ? 403 : 204, headers: { "access-control-allow-origin": "http://127.0.0.1:3107" } });
  });
  await mockStatus(page, ["processed"]);
  await page.goto("/");
  await choose(page);
  await page.getByRole("button", { name: "Upload CSV" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "expired" })).toBeVisible();
  await page.getByRole("button", { name: "Retry upload" }).click();
  await expect(page.getByRole("status")).toContainText("Ingestion complete");
  expect(presign.count()).toBe(2);
  expect(new Set(presign.keys).size).toBe(1);
});

test("backend failure is announced and rapid duplicate clicks issue one presign", async ({ page }) => {
  let calls = 0;
  await page.route(`${API}/uploads`, async (route) => { calls += 1; await route.fulfill({ status: 503, body: "unavailable" }); });
  await page.goto("/");
  await choose(page);
  await page.getByRole("button", { name: "Upload CSV" }).dblclick();
  await expect(page.getByRole("alert").filter({ hasText: "The request could not be completed." })).toBeVisible();
  expect(calls).toBe(1);
});

test("drag-drop works with keyboard-friendly controls and reduced motion", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await page.locator(".border-dashed").evaluate((target, content) => {
    const transfer = new DataTransfer();
    transfer.items.add(new File([content], "dropped.csv", { type: "text/csv" }));
    target.dispatchEvent(new DragEvent("drop", { bubbles: true, dataTransfer: transfer }));
  }, CSV);
  await expect(page.getByTestId("selected-file")).toContainText("dropped.csv");
  await expect(page.getByRole("button", { name: "Upload CSV" })).toBeEnabled();
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).scrollBehavior)).toBe("auto");
});

test("interrupted status polling can recover and reload by batch URL", async ({ page }) => {
  await mockPresign(page);
  await page.route(STORAGE, (route) => route.fulfill({ status: 204, headers: {
    "access-control-allow-origin": "http://127.0.0.1:3107",
  } }));
  let checks = 0;
  await page.route(`${API}/uploads/11111111-1111-4111-8111-111111111111`, (route) => {
    checks += 1;
    if (checks <= 3) return route.fulfill({ status: 503, body: "temporarily unavailable" });
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
      batch_id: "11111111-1111-4111-8111-111111111111", status: "processed",
      total_rows: 1, accepted_rows: 1, rejected_rows: 0, errors: {},
    }) });
  });
  await page.goto("/");
  await choose(page);
  await page.getByRole("button", { name: "Upload CSV" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "The request could not be completed." })).toBeVisible({ timeout: 20_000 });
  await page.getByRole("button", { name: "Refresh status" }).click();
  await expect(page.getByRole("status")).toContainText("Ingestion complete");
  expect(page.url()).toContain("?batch=11111111-1111-4111-8111-111111111111");
  await page.reload();
  await expect(page.getByRole("status")).toContainText("Ingestion complete");
  expect(checks).toBeGreaterThanOrEqual(5);
});
