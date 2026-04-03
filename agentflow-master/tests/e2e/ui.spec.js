const fs = require("fs");
const path = require("path");
const { test, expect } = require("@playwright/test");

const uiPipeline = fs.readFileSync(path.join(__dirname, "fixtures", "ui-pipeline.yaml"), "utf8");
const cancelPipeline = fs.readFileSync(path.join(__dirname, "fixtures", "cancel-pipeline.yaml"), "utf8");

test("validates, runs, retries, and reruns a DAG from the web UI", async ({ page }) => {
  await page.goto("/");
  await page.locator("#pipeline-input").fill(uiPipeline);
  await page.getByRole("button", { name: "Validate" }).click();
  await expect(page.locator("#banner")).toContainText("Pipeline validated");

  await page.getByRole("button", { name: "Run pipeline" }).click();
  await expect(page.locator("#run-status")).toContainText(/queued|running|completed/);
  await expect(page.locator(".graph-node").filter({ hasText: "plan" })).toBeVisible();
  await expect.poll(async () => (await page.locator("#run-status").textContent())?.trim()).toMatch(/completed/);

  await page.locator(".graph-node", { hasText: "plan" }).click();
  await expect(page.locator("#detail")).toContainText("Attempt 1");
  await expect(page.locator("#detail")).toContainText("Attempt 2");
  await page.getByRole("button", { name: "Launch" }).click();
  await expect(page.locator("#detail")).toContainText('"command": [');
  await expect(page.locator("#detail")).toContainText("tests/e2e/bin/codex");
  await page.getByRole("button", { name: "Stdout" }).click();
  await expect(page.locator("#detail")).toContainText("plan success");

  const previousRunId = (await page.locator(".run-item.active .mono").textContent()).trim();
  await page.getByRole("button", { name: "Rerun" }).click();
  await expect(page.locator("#banner")).toContainText("Rerun queued");
  await expect.poll(async () => ((await page.locator(".run-item.active .mono").textContent()) || "").trim()).not.toBe(previousRunId);
});

test("cancels a running DAG from the web UI", async ({ page }) => {
  await page.goto("/");
  await page.locator("#pipeline-input").fill(cancelPipeline);
  await page.getByRole("button", { name: "Run pipeline" }).click();
  await expect(page.locator("#run-status")).toContainText(/queued|running/);
  await page.getByRole("button", { name: "Cancel" }).click();
  await expect(page.locator("#banner")).toContainText("Cancellation requested");
  await expect.poll(async () => (await page.locator("#run-status").textContent())?.trim()).toMatch(/cancelled/);
  await page.locator(".graph-node", { hasText: "slow" }).click();
  await expect(page.locator("#detail")).toContainText("cancelled");
});
