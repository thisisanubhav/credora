import { expect, test } from "@playwright/test";
import { resolve } from "node:path";

const API = "http://127.0.0.1:8000";
const STORAGE = "http://127.0.0.1:4566/loan-engine-local";
const OUT = resolve(process.cwd(), "../../artifacts/m7");
const CSV = "user_id,email,monthly_income,credit_score,employment_status,age\nsynthetic-1,test@example.invalid,50000,710,Salaried,30\n";

test("capture sanitized desktop, progress, completion, errors, and mobile states", async ({ page }) => {
  await page.goto("/");
  // Keep Next.js development tooling out of UI evidence; this does not hide application elements.
  await page.addStyleTag({ content: "nextjs-portal { display: none !important; }" });
  await page.screenshot({ path: `${OUT}/initial-desktop.png`, fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: `${OUT}/initial-mobile.png`, fullPage: true });
  await page.setViewportSize({ width: 1280, height: 900 });

  await page.route(`${API}/uploads`, (route) => route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({
    batch_id: "11111111-1111-4111-8111-111111111111", expires_in: 600,
    upload: { url: STORAGE, fields: { key: "uploads/synthetic/file.csv", "Content-Type": "text/csv", policy: "sanitized" } },
  }) }));
  await page.route(STORAGE, async (route) => {
    await new Promise((done) => setTimeout(done, 1800));
    await route.fulfill({ status: 204, headers: { "access-control-allow-origin": "http://127.0.0.1:3107" } });
  });
  let status = "processed";
  await page.route(`${API}/uploads/11111111-1111-4111-8111-111111111111`, (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
    batch_id: "11111111-1111-4111-8111-111111111111", status,
    total_rows: status === "processed" ? 1 : 2, accepted_rows: 1,
    rejected_rows: status === "processed" ? 0 : 1, errors: {},
  }) }));
  await page.route(`${API}/uploads/11111111-1111-4111-8111-111111111111/errors*`, (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
    batch_id: "11111111-1111-4111-8111-111111111111", offset: 0, limit: 20,
    errors: [{ row: 3, codes: ["invalid_email"] }],
  }) }));

  await page.locator("#csv-file").setInputFiles({ name: "synthetic.csv", mimeType: "text/csv", buffer: Buffer.from(CSV) });
  await page.getByRole("button", { name: "Upload CSV" }).click();
  await expect(page.getByRole("progressbar", { name: "CSV upload progress" })).toBeVisible();
  await page.screenshot({ path: `${OUT}/upload-progress.png`, fullPage: true });
  await expect(page.getByRole("status")).toContainText("Ingestion complete", { timeout: 15_000 });
  await page.screenshot({ path: `${OUT}/processing-complete.png`, fullPage: true });

  status = "processed_with_errors";
  await page.getByRole("button", { name: "Refresh status" }).click();
  await expect(page.getByRole("status")).toContainText("Partially complete");
  await expect(page.getByText("Enter a valid email address.")).toBeVisible();
  await page.screenshot({ path: `${OUT}/validation-errors.png`, fullPage: true });
});
