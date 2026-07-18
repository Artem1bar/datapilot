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

test("a pending plan card stays bound to its own session across switches", async ({ page }) => {
  await page.goto("/");
  await uploadFixture(page);
  await sendMessage(page, "Clean the data");
  await expect(page.getByText("Cleaning Plan", { exact: true })).toBeVisible({ timeout: 60_000 });

  // Switch away to a brand-new session: the plan card must not follow.
  await page.getByRole("button", { name: "New session", exact: true }).click();
  await expect(page.getByText("Cleaning Plan", { exact: true })).not.toBeVisible();

  // Switch back and apply — the results must land in the owning session.
  await page.getByText(/messy_people\.csv/).first().click();
  await expect(page.getByText("Cleaning Plan", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: /^Apply \d+ steps?$/ }).click();
  await expect(page.getByText("Cleaning Complete", { exact: true })).toBeVisible({ timeout: 90_000 });
});

test("a refresh right after applying re-attaches and still shows the results", async ({
  page,
}) => {
  await page.goto("/");
  await uploadFixture(page);
  await sendMessage(page, "Clean the data");
  await expect(page.getByText("Cleaning Plan", { exact: true })).toBeVisible({ timeout: 60_000 });

  // The card flips to "Applied" optimistically, before the job dispatch —
  // wait for the apply POST itself so the job is registered for re-attach
  // (a human can't refresh inside that window; a test can).
  const applyResponse = page.waitForResponse(
    (r) => r.url().includes("/apply") && r.request().method() === "POST",
  );
  await page.getByRole("button", { name: /^Apply \d+ steps?$/ }).click();
  await expect(page.getByRole("button", { name: "Applied" })).toBeVisible();
  await applyResponse;
  await page.waitForTimeout(300); // let the store persist the registration

  // Refresh: whether the job is still running or already done, the
  // mount-time re-attach must deliver the results cards.
  await page.reload();
  await expect(page.getByText("Cleaning Complete", { exact: true })).toBeVisible({ timeout: 90_000 });
  await expect(page.getByRole("button", { name: /download cleaned data/i })).toBeVisible();
});
