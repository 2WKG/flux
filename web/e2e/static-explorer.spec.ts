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

/** Content-Security-Policy violations the page itself reported. */
const violations = new WeakMap<Page, string[]>();

test.beforeEach(async ({ page }) => {
  const requests: string[] = [];
  recorded.set(page, requests);
  // Both events: a request the CSP blocks may never reach `request`, so a
  // reintroduced third-party call could otherwise slip past the origin filter.
  page.on("request", (request) => requests.push(request.url()));
  page.on("requestfailed", (request) => requests.push(request.url()));

  const reported: string[] = [];
  violations.set(page, reported);
  await page.exposeFunction("__fluxCspViolation", (uri: string) => { reported.push(uri); });
  await page.addInitScript(() => {
    document.addEventListener("securitypolicyviolation", (event) => {
      (window as unknown as { __fluxCspViolation: (uri: string) => void })
        .__fluxCspViolation(`${event.violatedDirective} ${event.blockedURI}`);
    });
  });
});

/**
 * **There is no sanctioned off-origin host any more.** This used to carry a
 * two-entry exception for `fonts.googleapis.com` and `fonts.gstatic.com`,
 * because `web/src/styles.css:1` imported a Google Fonts stylesheet and the
 * "offline" demo made three third-party requests on every load. Joshua's
 * decision of 2026-09-06 dropped the webfonts for the system stack the repo's
 * own visual guide names, so the exception is gone and the assertion is now
 * simply: nothing leaves the origin.
 *
 * The App *is* server-backed and does call `/health`, `/scenarios/{id}`,
 * `/layers/{name}` and `/api/v1/grid/layers/{layer}` — same-origin, every one,
 * which is what `connect-src 'self'` permits and what this asserts.
 */
async function expectSameOriginOnly(page: Page): Promise<void> {
  const baseOrigin = new URL(page.url()).origin;
  const requests = recorded.get(page) ?? [];
  const offOrigin = requests.filter((url) => new URL(url).origin !== baseOrigin);
  expect(offOrigin).toEqual([]);
  // And the policy itself saw nothing to block: a request the CSP stopped before
  // it reached the network is still an off-origin request the page tried to make.
  expect(violations.get(page) ?? []).toEqual([]);
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

test("the chat dock hosts the real evidence surface and states its own unavailability", async ({ page }) => {
  await page.goto("/");
  const dock = page.locator("section.chat-dock");
  await expect(dock).toHaveClass(/collapsed/);
  const toggle = dock.getByRole("button", { name: /Ask about visible evidence/i });
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  // Nothing served this origin an API, so the dock says so rather than offering
  // a Send button that would do nothing.
  await expect(dock.getByText(/Not available in this offline build/i)).toBeVisible();

  await toggle.click();
  await expect(dock).toHaveClass(/expanded/);
  // The real dock, the real run trace, the real result surface, and the named
  // failure state -- not the placeholder paragraphs this dock used to hold.
  await expect(dock.locator("section.flux-chat")).toBeVisible();
  await expect(dock.getByText(/No messages yet\. Your question will include the visible context above\./i)).toBeVisible();
  await expect(dock.locator("section.run-trace")).toBeVisible();
  await expect(dock.getByText(/No answer results are available\./i)).toBeVisible();
  await expect(dock.locator("section.failure-state")).toBeVisible();
  // The Send button is disabled while no endpoint has answered.
  await expect(dock.getByRole("button", { name: "Send" })).toBeDisabled();

  await dock.getByRole("button", { name: /Collapse/i }).click();
  await expect(dock).toHaveClass(/collapsed/);
  await expectSameOriginOnly(page);
});

test("the physical-inventory map is mounted inside the one App, with its disclosures", async ({ page }) => {
  await page.goto("/");
  const panel = page.getByLabel("Source-backed physical inventory");
  await expect(panel).toBeVisible();
  // The map is the merged #213 foundation, drawn once. It loads in the browser,
  // so this waits for the real renderer rather than the server-rendered slot.
  await expect(panel.getByLabel("Map and renderer status")).toBeVisible({ timeout: 20_000 });
  await expect(panel.locator("canvas.maplibregl-canvas")).toBeVisible();
  // And there is no second, mis-projected geometry surface over it.
  await expect(panel.locator("svg.grid-geometry-overlay")).toHaveCount(0);

  // The inventory API is not served by this origin, so the panel names the
  // refusal instead of showing an empty map as if it were an empty state.
  await expect(panel.getByLabel("Coverage and geometry availability")).toBeVisible();
  await expect(panel.locator(".grid-map-note")).toContainText(/Unavailable|Request failed|Requesting the source-backed inventory release/);
  await expectSameOriginOnly(page);
});

test("every layer is disclosed unavailable with the producer reason, never hidden", async ({ page }) => {
  await page.goto("/");
  const controls = page.locator("section.layer-controls");
  await expect(controls).toBeVisible();
  const rows = controls.locator("li.layer-row");
  await expect(rows).toHaveCount(6);
  for (const row of await rows.all()) {
    // Nothing on this origin serves `/layers/{name}`, so the topology layer's
    // request fails and the other five have no server layer bound at all. Both
    // are frozen tokens, and neither may be shown as available or simply hidden.
    const status = await row.getAttribute("data-status");
    expect(["unavailable", "request_failed"]).toContain(status);
    await expect(row.locator("p.layer-reason")).not.toBeEmpty();
    await expect(row.locator("input[type=checkbox]")).toBeDisabled();
  }
  await expect(page.getByLabel("Layer status legend")).toBeVisible();
  await expectSameOriginOnly(page);
});

test("the explainer deep-links and navigation retain URL state without a document reload", async ({ page }) => {
  await page.addInitScript(() => {
    window.sessionStorage.setItem("flux-document-loads", String(Number(window.sessionStorage.getItem("flux-document-loads") ?? 0) + 1));
  });

  await page.goto("/explainer?scenario=uri_2021&h=3#method");
  await expect(page.getByRole("heading", { name: /How the math works/i })).toBeVisible();
  await expect(page).toHaveTitle("Flux | How the math works");
  await expect(page.getByRole("link", { name: "How the math works" })).toHaveAttribute("aria-current", "page");
  await expect(page.locator("main")).toHaveAttribute("data-source-status", "unavailable");
  expect(await page.evaluate(() => window.sessionStorage.getItem("flux-document-loads"))).toBe("1");

  await page.getByRole("link", { name: "Scenario explorer" }).click();
  await expect(page.getByRole("heading", { name: /Where does 300 MW cut the most unmet demand/i })).toBeVisible();
  await expect(page).toHaveURL(/\/?scenario=uri_2021&h=3#method$/);
  await expect(page).toHaveTitle("Flux | Resilience desk");
  await expect(page.getByRole("link", { name: "Scenario explorer" })).toHaveAttribute("aria-current", "page");
  expect(await page.evaluate(() => window.sessionStorage.getItem("flux-document-loads"))).toBe("1");

  await page.goBack();
  await expect(page.getByRole("heading", { name: /How the math works/i })).toBeVisible();
  await expect(page).toHaveTitle("Flux | How the math works");
  await page.goForward();
  await expect(page.getByRole("heading", { name: /Where does 300 MW cut the most unmet demand/i })).toBeVisible();
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
