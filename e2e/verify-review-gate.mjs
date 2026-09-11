// Drives the running dev stack (API :8011, web :3013) through the review gate
// and captures what a person actually sees. Verification only — throwaway.
//
// Seeds the session store rather than uploading: this machine's disk is too
// full for MinIO to accept an object, and the gate under test does not touch
// storage — the catalogue and validate calls it makes are real.
import { chromium } from "@playwright/test";

const OUT =
  "/private/tmp/claude-501/-Users-artembaranovski-Projects-datapilot/d602e2d0-4ec2-46f7-b16f-2318c1da077a/scratchpad";
const DS = "11111111-2222-3333-4444-555555555555";

const log = (...a) => console.log("•", ...a);

const seeded = (() => {
  const now = new Date().toISOString();
  const sid = "verify-session";
  return {
    state: {
      activeSessionId: sid,
      sessions: [
        { id: sid, title: "Review gate", subtitle: "", createdAt: now, updatedAt: now, pinned: false, datasetId: DS },
      ],
      messagesBySession: {
        [sid]: [
          { id: "m1", role: "user", content: "Clean the data", card: null, timestamp: now },
          {
            id: "m2",
            role: "assistant",
            content: "",
            timestamp: now,
            card: {
              type: "cleaning_plan",
              summary:
                "Amount arrives padded with spaces and carries one value far outside its own spread. Nothing has been changed yet.",
              datasetId: DS,
              columns: ["Amount", "City"],
              steps: [
                { operation: "clean_column_names", column: null, params: {}, description: "Step 1: Normalise the column names", rationale: "Two headers carry trailing spaces.", confidence: 0.95 },
                { operation: "strip_whitespace", column: "Amount", params: {}, description: "Step 2: Strip whitespace from Amount", rationale: "Values arrive padded.", confidence: 0.9 },
                { operation: "cap_extreme_values", column: "Amount", params: { max_value: 5000 }, description: "Step 3: Cap Amount at 5000", rationale: "One value is 100x the 99th percentile.", confidence: 0.62 },
              ],
            },
          },
        ],
      },
      activeCleaningJobsBySession: {},
    },
    version: 0,
  };
})();

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1180, height: 1000 } });
page.on("console", (m) => m.type() === "error" && console.log("  [console error]", m.text()));

await page.addInitScript((state) => {
  localStorage.setItem("datatiger-sessions", JSON.stringify(state));
}, seeded);

await page.goto("http://localhost:3013");
await page.getByText("Cleaning Plan", { exact: true }).waitFor({ timeout: 30_000 });
log("plan card rendered");
log("gate copy:", await page.getByText(/nothing runs until you approve it/i).isVisible());
log("destructive step flagged:", await page.getByText("removes data").first().isVisible());

const card = page.locator("div.rounded-xl").first();
await page.waitForTimeout(700); // let the stagger settle
await card.screenshot({ path: `${OUT}/1-review-card.png` });

// ── Edit: open step 3 and check the ceiling is an editable, typed field ──
await page.getByRole("button", { name: /edit step 3 settings/i }).click();
const ceiling = page.getByLabel(/^Ceiling/);
await ceiling.waitFor();
log("ceiling currently:", await ceiling.inputValue());
const columnField = page.getByLabel(/target column/i);
log("column picker offers:", JSON.stringify(await columnField.locator("option").allTextContents()));
await page.waitForTimeout(300);
await card.screenshot({ path: `${OUT}/2-step-editor.png` });

await ceiling.fill("250");
await ceiling.blur();
await page.getByText("edited").first().waitFor();
log("edit marked on the step");

// ── Blocking: clear the required ceiling, Apply must refuse ──
await ceiling.fill("");
await ceiling.blur();
await page.getByText(/needs ceiling/i).waitFor();
const applyBtn = page.getByRole("button", { name: /^Apply \d+ steps?$/ });
log("apply blocked with the value missing:", await applyBtn.isDisabled());
await page.waitForTimeout(300);
await card.screenshot({ path: `${OUT}/3-blocked.png` });

// ── Adding a step the planner never proposed ──
await ceiling.fill("250");
await ceiling.blur();
await page.getByRole("button", { name: /^Add a step$/ }).click();
await page.waitForTimeout(400);
await card.screenshot({ path: `${OUT}/4-add-step-picker.png` });
await page.getByRole("button", { name: /^Remove duplicate rows/ }).click();
await page.getByText("you added").waitFor();
log("added step appears, marked as the user's");

await page.waitForFunction(
  () => {
    const b = [...document.querySelectorAll("button")].find((x) => /^Apply \d+ steps?$/.test(x.textContent ?? ""));
    return b && !b.disabled;
  },
  { timeout: 10_000 },
);
log("apply re-enabled once the plan is complete");
await page.waitForTimeout(300);
await card.screenshot({ path: `${OUT}/5-edited-plan.png` });

// ── The server's own pre-flight, observed on the wire ──
const validateCalls = [];
page.on("response", (r) => {
  if (r.url().includes("/plan/validate")) validateCalls.push(r.status());
});
await applyBtn.click();
await page.waitForTimeout(2500);
log("server pre-flight calls:", JSON.stringify(validateCalls));
log("card locked after approval:", await page.getByRole("button", { name: /Applied/ }).isVisible());
await page.screenshot({ path: `${OUT}/6-after-approval.png` });

await browser.close();
log("done");
