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
 *  3. The API behind the origin is the real `copilot.app`, booted by
 *     `scripts/e2e-stack.mjs`. A fresh clone has no `data/duck/grid.duckdb`, so
 *     the data routes answer the API's own named `unavailable` envelopes rather
 *     than fabricated rows -- and the assertions below pin *that* reason
 *     (`API_DATABASE_REFUSAL`), not merely "something said unavailable". With
 *     no API the refusal would come from `web/server.mjs` itself and read
 *     `no_api_origin_configured`, so killing the API turns this suite red
 *     instead of leaving it quietly green.
 *
 * KNOWN RED, and deliberately not silenced -- two causes, neither this file's
 * to decide:
 *
 *  a. CSP vs WebAssembly. Every case below asserts the page reported no CSP
 *     violation. At master `eac05eb` all nine failed with
 *     `script-src wasm-eval`: `web/server.mjs`'s policy is `script-src 'self'`,
 *     which forbids WebAssembly compilation, while the glTF path bundles
 *     meshoptimizer's decoder -- it probes for SIMD with `WebAssembly.validate`
 *     then calls `WebAssembly.instantiate` on a bundled buffer, and Chromium
 *     refuses both. The one directive that would permit it is
 *     `'wasm-unsafe-eval'` (WebAssembly compilation only: no `eval`, no
 *     `new Function`, no off-origin source). Adding it is a security decision
 *     for the owner of that policy, so it is NOT taken here. Measured at
 *     `eac05eb` with the API booted: with the directive added locally all 12
 *     cases pass; without it 7 fail on this assertion and 5 pass.
 *  b. The page moved. At master `5325957` (#358, 2WKG-486) `/` renders the
 *     ACTIVSg2000 Texas topology, not the Minnesota five-bus synthetic
 *     explorer, so most locators below find nothing and no map mounts on `/`
 *     at all -- which is also why (a) no longer fires there. Which surface owns
 *     `/`, and where this proof should now point, is a product decision, not a
 *     test fix. The cases are left failing rather than weakened, skipped, or
 *     marked expected-failure.
 *
 * The one case here that survives (b) is the chat dock, and it passes: it is
 * the case that pins the API's own refusal, so it is live proof that the stack
 * below really boots `copilot.app`.
 */

/**
 * The message `copilot/` emits when the DuckDB artifact is absent. Only a
 * running API produces it: the origin's own no-upstream envelope says
 * "no Copilot API origin is configured for this deployment" instead.
 */
const API_DATABASE_REFUSAL = /The (?:configured )?database artifact is unavailable\./;

const SYNTHETIC_NAV_SUMMARY = /Synthetic · fixture source · no asserted topology · no API required/i;
const SYNTHETIC_STATUS_PILL = /Synthetic five-bus preview · not Minnesota data/i;
/** Any claim of source support over a synthetic fixture, in any spelling. */
const SOURCE_BACKED_CLAIM = /source[_ -]?backed|source[_ -]?supported|source[_ -]?screened|Minnesota coverage/i;
/** The one surface on this page that *is* source-supported and says so honestly. */
const SOURCE_BACKED_PANEL = "Source-backed physical inventory";

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
  // Scoped to the synthetic surface, and only because the App is server-backed:
  // the MN physical-inventory panel beside it is a genuinely source-supported
  // release, so with the API up it legitimately renders "Scene state:
  // source_supported" and "No source-backed statewide line denominator ... is
  // available." A page-wide sweep would read those as the synthetic fixture
  // claiming source support, which is the opposite of what this guards. The
  // guard still fails if the synthetic explorer, its inspector, its status pill
  // or its disclosure ever claims it.
  const syntheticText = await page.evaluate((panelLabel) => {
    const main = document.querySelector("main");
    if (!main) return "";
    const clone = main.cloneNode(true) as HTMLElement;
    for (const node of clone.querySelectorAll(`[aria-label="${panelLabel}"]`)) node.remove();
    return clone.textContent ?? "";
  }, SOURCE_BACKED_PANEL);
  expect(syntheticText).not.toMatch(SOURCE_BACKED_CLAIM);
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
  // The API *is* served on this origin, and it answered `/health` with its own
  // named unavailable envelope (no DuckDB in a clean clone). `askAvailable` is
  // derived from that probe, so the dock still refuses -- and it refuses for the
  // reason the API gave, not because nothing was listening.
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
  // The named state comes from the API's `/health` envelope. If the API is not
  // running, this reads the origin's `no_api_origin_configured` copy instead and
  // this assertion fails -- which is the point.
  await expect(dock.locator("section.failure-state")).toContainText(API_DATABASE_REFUSAL);
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

  // The inventory API *is* served by this origin now, and the MN physical
  // inventory is a release artifact rather than a DuckDB table, so it answers
  // with real records. The panel must therefore state a real, counted coverage
  // and the release it read -- never a blank map, and never a refusal it no
  // longer has. Without the API this note reads the unavailable copy and fails.
  await expect(panel.getByLabel("Coverage and geometry availability")).toBeVisible();
  const note = panel.locator(".grid-map-note");
  await expect(note).toContainText(/\d+ rendered from \d+ loaded records/, { timeout: 20_000 });
  await expect(note).toContainText(/Release SHA-256: [0-9a-f]{64}/);
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
  // The topology layer is the one layer with a server read route. Its reason is
  // the API's own database refusal, so this row proves the request reached
  // `copilot.app` and came back named -- a row that merely says "unavailable"
  // cannot tell a booted API from an absent one.
  // Web-first, not a sample: the topology reason arrives with the `/layers`
  // answer, after the row has already rendered its pre-request state.
  await expect(rows.locator("p.layer-reason").filter({ hasText: API_DATABASE_REFUSAL })).toHaveCount(1);
  await expect(rows.locator("p.layer-reason").filter({ hasText: /no Copilot API origin is configured/i })).toHaveCount(0);
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
