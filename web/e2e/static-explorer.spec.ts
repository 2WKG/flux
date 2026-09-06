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

const SYNTHETIC_NAV_SUMMARY = /Synthetic ACTIVSg2000 static topology · model API required/i;
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
  await expect(page.getByText(SOURCE_BACKED_CLAIM)).toHaveCount(0);
}

test("the static explorer exposes the synthetic Texas topology boundary", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "ACTIVSg2000 network geometry" })).toBeVisible();
  await expectSyntheticProvenance(page);
  await expect(page.getByLabel("Full synthetic Texas topology workspace", { exact: true })).toBeVisible();
  await expect(page.getByText(/Texas model topology unavailable/i)).toBeVisible();

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

test("the Texas topology workspace names an unavailable model response", async ({ page }) => {
  await page.goto("/");
  const workspace = page.getByLabel("Full synthetic Texas topology workspace", { exact: true });
  await expect(workspace).toBeVisible();
  await expect(workspace.getByRole("status")).toContainText(/Texas model topology unavailable/i);
  await expect(workspace.getByRole("status")).toContainText(/no Copilot API origin is configured/i);
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
  await expect(page.getByRole("region", { name: "Layers and evidence" })).toBeVisible();
  await expectSameOriginOnly(page);
});

test("the explainer deep-links and navigation retain URL state without a document reload", async ({ page }) => {
  await page.addInitScript(() => {
    window.sessionStorage.setItem("flux-document-loads", String(Number(window.sessionStorage.getItem("flux-document-loads") ?? 0) + 1));
  });

  await page.goto("/explainer?scenario=uri_2021&h=3#method");
  await expect(page.getByRole("heading", { name: "How the math works, and how much of it is real." })).toBeVisible();
  await expect(page).toHaveTitle("Flux | How the math works");
  await expect(page.getByRole("link", { name: "How the math works" })).toHaveAttribute("aria-current", "page");
  await expect(page.locator("main")).toHaveAttribute("data-source-status", "unavailable");
  expect(await page.evaluate(() => window.sessionStorage.getItem("flux-document-loads"))).toBe("1");

  await page.getByRole("link", { name: "Scenario explorer" }).click();
  await expect(page.getByRole("heading", { name: "ACTIVSg2000 network geometry" })).toBeVisible();
  await expect(page).toHaveURL(/\/?scenario=uri_2021&h=3#method$/);
  await expect(page).toHaveTitle("Flux | Resilience desk");
  await expect(page.getByRole("link", { name: "Scenario explorer" })).toHaveAttribute("aria-current", "page");
  expect(await page.evaluate(() => window.sessionStorage.getItem("flux-document-loads"))).toBe("1");

  await page.goBack();
  await expect(page.getByRole("heading", { name: "How the math works, and how much of it is real." })).toBeVisible();
  await expect(page).toHaveTitle("Flux | How the math works");
  await page.goForward();
  await expect(page.getByRole("heading", { name: "ACTIVSg2000 network geometry" })).toBeVisible();
  await expectSameOriginOnly(page);
});

test("the data disclosure identifies the Texas model boundary", async ({ page }) => {
  await page.goto("/");
  const disclosure = page.getByRole("button", { name: "Data, units & limits" });
  await disclosure.click();
  const dialog = page.getByRole("dialog", { name: "Data disclosure" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText("tx:synthetic-topology:activsg2000-current-v1", { exact: false })).toBeVisible();
  await expect(dialog.getByText(/synthetic ACTIVSg2000 topology; not a physical asset/i)).toBeVisible();
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
