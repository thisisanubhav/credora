import { expect, test } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";

// Opt-in: requires local FastAPI, LocalStack, worker, dispatcher and published n8n B/C.
test("real browser upload reaches local ingestion and exposes a batch reference", async ({ page }) => {
  expect(process.env.NEXT_PUBLIC_ENABLE_DEMO_UPLOAD).toBe("1");
  const output = resolve(process.cwd(), process.env.QA_SCREENSHOT_DIR ?? "../../artifacts/m9");
  mkdirSync(output, { recursive: true });
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Upload applicant data" })).toBeVisible();
  await page.screenshot({ path: `${output}/real-initial-desktop.png`, fullPage: true });
  await page.setViewportSize({ width: 768, height: 1024 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(768);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.screenshot({ path: `${output}/real-initial-mobile.png`, fullPage: true });
  await page.setViewportSize({ width: 1280, height: 900 });

  const csv = "user_id,email,monthly_income,credit_score,employment_status,age\n"
    + "one,one@example.com,50000,710,Salaried,30\n"
    + "two,two@example.com,50000,760,Salaried,30\n"
    + "none,none@example.com,50000,699,Salaried,30\n";
  await page.locator("#csv-file").setInputFiles({
    name: "qa-synthetic.csv", mimeType: "text/csv", buffer: Buffer.from(csv),
  });
  await page.getByRole("checkbox", { name: /Local synthetic demonstration only/ }).check();
  await page.getByRole("button", { name: "Upload CSV" }).click();
  await expect(page.getByRole("progressbar", { name: "CSV upload progress" })).toBeVisible();
  await page.screenshot({ path: `${output}/real-upload-state.png`, fullPage: true });
  await expect(page.getByTestId("batch-id")).toBeVisible();
  await expect(page.getByRole("status").first()).toContainText(/Ingestion complete|Checking eligibility|Matches found/, { timeout: 30_000 });
  await page.screenshot({ path: `${output}/real-ingestion-complete.png`, fullPage: true });
  const batchId = await page.getByTestId("batch-id").textContent();
  expect(batchId).toMatch(/^[0-9a-f-]{36}$/);
  expect(errors).toEqual([]);
  console.log(`QA_REAL_BATCH_ID=${batchId}`);
});
