import { test, expect, type Page } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const FIXTURE = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
  "fixtures",
  "messy_people.csv",
);

async function uploadFixture(page: Page) {
  await page.setInputFiles('input[type="file"]', FIXTURE);
  await expect(page.getByText(/messy_people\.csv.*is ready/i)).toBeVisible({
    timeout: 60_000,
  });
}

async function sendMessage(page: Page, text: string) {
  const input = page.getByPlaceholder(/ask anything about your data/i);
  await input.fill(text);
  await input.press("Enter");
}

test("golden path: upload → plan → toggle → apply → validate → results → compare → recipe", async ({
  page,
}) => {
  await page.goto("/");

  // ── Upload + profile ──
  await uploadFixture(page);

  // ── Plan (stubbed AI) ──
  await sendMessage(page, "Clean the data");
  await expect(page.getByText("Cleaning Plan", { exact: true })).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText(/strip leading\/trailing whitespace/i)).toBeVisible();
  await expect(page.getByText("2 of 2 selected")).toBeVisible();

  // ── The gate: toggling steps changes the apply count; nothing auto-applies ──
  const toggles = page.getByRole("button", { name: /exclude this step/i });
  await toggles.last().click();
  await expect(page.getByText("1 of 2 selected")).toBeVisible();
  await expect(page.getByRole("button", { name: "Apply 1 step" })).toBeVisible();
  await page.getByRole("button", { name: /include this step/i }).click();
  await expect(page.getByText("2 of 2 selected")).toBeVisible();

  // ── Apply ──
  await page.getByRole("button", { name: /^Apply 2 steps$/ }).click();
  await expect(page.getByRole("button", { name: "Applied" })).toBeVisible();

  // ── Validation + results ──
  await expect(page.getByText(/2\/2 checks passed/i)).toBeVisible({ timeout: 90_000 });
  await expect(page.getByText("Cleaning Complete", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: /download cleaned data/i })).toBeVisible();

  // ── Before/after comparison (real endpoint, no AI) ──
  await page.getByRole("button", { name: /see what changed/i }).click();
  await expect(page.getByText("Dataset Comparison")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("Sample changes")).toBeVisible();

  // ── Save as recipe ──
  await page.getByRole("button", { name: /save as recipe/i }).click();
  await page.getByPlaceholder(/standard orders cleanup/i).fill("E2E recipe");
  await page.getByRole("button", { name: "Save recipe" }).click();
  await expect(page.getByText(/recipe.*E2E recipe.*saved/i)).toBeVisible({ timeout: 30_000 });

  // ── Apply the recipe from the + menu (validates + runs a second clean) ──
  await page.getByRole("button", { name: "Open attach menu" }).click();
  await page.getByRole("menuitem", { name: /apply a recipe/i }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText("E2E recipe")).toBeVisible({ timeout: 30_000 });
  await dialog.getByRole("button", { name: "Apply" }).first().click();
  await expect(page.getByText("Cleaning Complete", { exact: true }).nth(1)).toBeVisible({ timeout: 90_000 });

  // ── Revert the recipe run ──
  await page.getByRole("button", { name: /revert to original/i }).last().click();
  await expect(page.getByText(/cleaning reverted/i)).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("Reverted", { exact: true })).toBeVisible();
});
