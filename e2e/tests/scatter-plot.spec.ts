import { test, expect, type Page } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

// 40 rows of units/revenue/region with one missing revenue, so the plot has a
// real fit, three color groups, and a stated exclusion.
const FIXTURE = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
  "fixtures",
  "sales_points.csv",
);

async function uploadFixture(page: Page) {
  await page.setInputFiles('input[type="file"]', FIXTURE);
  await expect(page.getByText(/sales_points\.csv.*is ready/i)).toBeVisible({
    timeout: 60_000,
  });
}

test("scatter plotter: pick two columns → computed plot in the chat and the panel (no AI)", async ({
  page,
}) => {
  await page.goto("/");
  await uploadFixture(page);

  // ── Open the plotter from the + menu ──
  await page.getByRole("button", { name: "Open attach menu" }).click();
  await page.getByRole("menuitem", { name: /scatter plot/i }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("heading", { name: "Scatter plot" })).toBeVisible();

  // Two numeric columns are preselected, but JSONB reorders the profile's
  // keys, so choose the axes explicitly rather than trusting that order.
  await expect(dialog.getByLabel("X axis")).toHaveValue(/./, { timeout: 30_000 });
  await dialog.getByLabel("X axis").selectOption("units");
  await dialog.getByLabel("Y axis").selectOption("revenue");
  await dialog.getByLabel("Color by").selectOption("region");
  await dialog.getByRole("button", { name: "Plot" }).click();

  // ── The request and the computed answer land in the conversation ──
  await expect(
    page.getByText("Scatter plot of revenue against units, colored by region"),
  ).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText(/over 39 complete rows \(1 excluded/)).toBeVisible();
  await expect(page.getByText(/OLS fit: revenue = /)).toBeVisible();

  // ── The chart card: one mark per row, the fitted line, the legend, the caption ──
  const card = page.locator(".recharts-wrapper").first();
  await expect(card).toBeVisible({ timeout: 30_000 });
  await expect(card.locator(".recharts-scatter-symbol")).toHaveCount(39);
  await expect(card.locator(".recharts-reference-line")).toHaveCount(1);
  await expect(page.getByText("OLS fit", { exact: true }).first()).toBeVisible();
  await expect(page.getByText(/n = 39 · R² = /).first()).toBeVisible();

  // ── The methods note records what ran (collapsed by default) ──
  await page.getByRole("button", { name: /^Methods/ }).click();
  await expect(page.getByText("scatter_with_fit").first()).toBeVisible();

  // ── The panel opened with the same chart ──
  await expect(page.getByText("Visualizations")).toBeVisible();
  await expect(page.locator(".recharts-wrapper")).toHaveCount(2);

  // ── The reading: what the fit says, its caveats, and questions to ask next ──
  await expect(page.getByText("Reading this plot").first()).toBeVisible();
  await expect(page.getByText(/strong positive linear association/).first()).toBeVisible();
  await expect(page.getByText(/not causation/).first()).toBeVisible();
  await expect(page.getByText(/pools all 3 groups of region/).first()).toBeVisible();

  // ── The panel's own button is the second way in; a bubble chart ──
  await page.getByRole("button", { name: "New scatter plot" }).click();
  const again = page.getByRole("dialog");
  await expect(again.getByLabel("X axis")).toHaveValue(/./, { timeout: 30_000 });
  await again.getByLabel("X axis").selectOption("units");
  await again.getByLabel("Y axis").selectOption("revenue");
  await again.getByLabel("Bubble size").selectOption("orders");
  await again.getByRole("button", { name: "Plot" }).click();
  await expect(
    page.getByText("Scatter plot of revenue against units, sized by orders", { exact: true }),
  ).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText(/Bubble area shows orders/).first()).toBeVisible();
  await expect(page.locator(".recharts-wrapper")).toHaveCount(4);

  // ── A suggested follow-up lands in the chat input, ready to send ──
  await page.getByRole("button", { name: /Spearman correlation between units and revenue/ }).last().click();
  await expect(page.getByPlaceholder(/ask anything about your data/i)).toHaveValue(
    "What is the Spearman correlation between units and revenue?",
  );

  // Optional: keep a picture of the finished state (e.g. for release notes).
  if (process.env.E2E_SCREENSHOT) {
    await page.screenshot({ path: process.env.E2E_SCREENSHOT });
  }
});
