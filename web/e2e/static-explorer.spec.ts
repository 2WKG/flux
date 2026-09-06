import { expect, test, type Page } from "@playwright/test";

/**
 * The browser proof for the static explorer.
 *
 * It builds the real dist, serves it with the real `server.mjs`, and drives a
 * real browser. Two rules govern what it asserts:
 *
 *  1. Provenance is pinned on the machine token the IA governs
 *     (`main[data-source-status]`, written from `deriveSourceTruth`), never on
 *     the prose around it. Relabelling the synthetic fixture as source-backed
 *     must fail here.
 *  2. The no-network claim is an allowlist over request *origins*, not a
 *     denylist over two path prefixes, and it is installed for every test.
 */

const SYNTHETIC_NAV_SUMMARY = /Synthetic · fixture source · no asserted topology · no API required/i;
const SYNTHETIC_STATUS_PILL = /Synthetic five-bus preview · not Minnesota data/i;
/** Any claim of source support over a synthetic fixture, in any spelling. */
const SOURCE_BACKED_CLAIM = /source[_ -]?backed|source[_ -]?supported|source[_ -]?screened|Minnesota coverage/i;

/** Every request the page made, recorded for the same-origin assertion. */
const recorded = new WeakMap<Page, string[]>();

test.beforeEach(async ({ page }) => {
  const requests: string[] = [];
  recorded.set(page, requests);
  page.on("request", (request) => requests.push(request.url()));
});

/**
 * The one off-origin dependency this build actually has: the Google Fonts
 * stylesheet `web/src/styles.css:1` imports, and the woff2 files it pulls.
 * It is listed here so the assertion states the exception instead of hiding
 * it behind a path pattern. Nothing else may leave the origin, and no request
 * may reach an `/ask` or `/api` path on any host.
 */
const SANCTIONED_OFF_ORIGINS = ["https://fonts.googleapis.com", "https://fonts.gstatic.com"];

/** Requests leave the page's origin only for the sanctioned font hosts. */
async function expectSameOriginOnly(page: Page): Promise<void> {
  const baseOrigin = new URL(page.url()).origin;
  const requests = recorded.get(page) ?? [];
  const unexpected = requests.filter((url) => {
    const origin = new URL(url).origin;
    return origin !== baseOrigin && !SANCTIONED_OFF_ORIGINS.includes(origin);
  });
  expect(unexpected).toEqual([]);
  // No agent, model, or data endpoint is contacted on any host.
  const api = requests.filter((url) => /^\/(ask|api)(\/|$)/.test(new URL(url).pathname));
  expect(api).toEqual([]);
}

/** The provenance tokens the product's honesty claim rests on. */
async function expectSyntheticProvenance(page: Page): Promise<void> {
  await expect(page.locator("main")).toHaveAttribute("data-source-status", "synthetic");
  await expect(page.getByText(SYNTHETIC_NAV_SUMMARY)).toBeVisible();
  await expect(page.getByText(SYNTHETIC_STATUS_PILL)).toBeVisible();
  await expect(page.getByText(SOURCE_BACKED_CLAIM)).toHaveCount(0);
}

test("the static explorer selects scenarios and keeps its synthetic label through every selection", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /Where does 300 MW cut the most unmet demand/i })).toBeVisible();
  await expectSyntheticProvenance(page);

  await page.getByRole("button", { name: /Candidate A/i }).first().click();
  await expect(page.getByText(/NETWORK STATE · CANDIDATE A/i)).toBeVisible();
  const inspector = page.locator("aside.inspector");
  // Wait on state only the post-click render can produce, then assert what survived it.
  await expect(inspector.getByText(/CANDIDATE A · \+\d+ MW AT/i)).toBeVisible();
  await expect(inspector.getByText(/MODELED UNMET DEMAND/i)).toBeVisible();
  await expectSyntheticProvenance(page);

  await page.getByRole("button", { name: /Candidate B/i }).first().click();
  await expect(page.getByText(/NETWORK STATE · CANDIDATE B/i)).toBeVisible();
  await expect(inspector.getByText(/CANDIDATE B · \+\d+ MW AT/i)).toBeVisible();
  await expectSyntheticProvenance(page);

  // Back to the reference run: the baseline copy is a different render, not a leftover.
  await page.getByRole("button", { name: /Baseline/i }).first().click();
  await expect(page.getByText(/NETWORK STATE · BASELINE/i)).toBeVisible();
  await expect(inspector.getByText(/NO CAPACITY ADDED/i)).toBeVisible();
  await expectSyntheticProvenance(page);

  await expectSameOriginOnly(page);
});

test("the chat dock states that it is unavailable rather than offering an answer", async ({ page }) => {
  await page.goto("/");
  const dock = page.locator("section.chat-dock");
  await expect(dock).toHaveClass(/collapsed/);
  const toggle = dock.getByRole("button", { name: /Ask about visible evidence/i });
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await expect(dock.getByText(/Not available in this offline build/i)).toBeVisible();

  await toggle.click();
  await expect(dock).toHaveClass(/expanded/);
  await expect(dock.getByText(/no Copilot endpoint, model result, or Minnesota artifact to query/i)).toBeVisible();
  await expect(dock.getByText(/must show its tool trail, citations, status, and limitations instead of inventing an answer/i)).toBeVisible();

  await dock.getByRole("button", { name: /Collapse/i }).click();
  await expect(dock).toHaveClass(/collapsed/);
  await expectSameOriginOnly(page);
});

test("keyboard selection works and the disclosure names the artifact it read", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: /Candidate B/i }).first().focus();
  await page.keyboard.press("Enter");
  await expect(page.getByText(/NETWORK STATE · CANDIDATE B/i)).toBeVisible();
  // Digit keys are the shell's own shortcut; 1 is the baseline run.
  await page.keyboard.press("1");
  await expect(page.getByText(/NETWORK STATE · BASELINE/i)).toBeVisible();

  const disclosure = page.getByRole("button", { name: "Data, units & limits" });
  await disclosure.click();
  const dialog = page.getByRole("dialog", { name: "Data disclosure" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText("flux:synthetic-scenario-input:v1", { exact: false })).toBeVisible();
  await expect(dialog.getByText(/not a Minnesota, Texas, ERCOT, MISO, or actual interconnection model/i)).toBeVisible();
  await expect(dialog.getByText(SOURCE_BACKED_CLAIM)).toHaveCount(0);

  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expectSameOriginOnly(page);
});

for (const viewport of [
  { name: "desktop", width: 1440, height: 900 },
  { name: "laptop", width: 1024, height: 768 },
  { name: "mobile", width: 390, height: 844 },
]) {
  test(`${viewport.name} keeps the static shell within its viewport after fonts settle`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await page.goto("/");
    await page.evaluate(async () => document.fonts.ready);
    const dimensions = await page.evaluate(() => ({
      clientWidth: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
    }));
    expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth);
    await expectSyntheticProvenance(page);
    await expectSameOriginOnly(page);
  });
}
