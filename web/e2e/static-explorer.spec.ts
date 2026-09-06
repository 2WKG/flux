import { expect, test } from "@playwright/test";

const fixtureDisclosure = /Synthetic five-bus fixture.*offline basemap.*no API required/i;

/**
 * The static demo is offline: every request it makes must be to its own origin,
 * and only for the shell, its favicon, or its own build assets. Any other URL --
 * a tile CDN, a font host, a style JSON, an API -- fails here. This is asserted
 * on the request origin, not on a path pattern, so no third-party host can be
 * permitted by construction.
 */
function assertNoRequestLeavesTheOrigin(requests: readonly { url: string; method: string }[], baseURL: string) {
  const offOrigin = requests.filter((request) => new URL(request.url).origin !== baseURL);
  expect(offOrigin.map((request) => request.url)).toEqual([]);
  for (const request of requests) {
    expect(request.method).toBe("GET");
    const url = new URL(request.url);
    expect(url.pathname === "/" || url.pathname === "/favicon.ico" || url.pathname.startsWith("/assets/")).toBeTruthy();
  }
}

test("static explorer supports scenario selection, inspection, and honest unavailable agent state", async ({ page }) => {
  const requests: { url: string; method: string }[] = [];
  page.on("request", (request) => requests.push({ url: request.url(), method: request.method() }));
  // A request the CSP blocks never reaches page.on("request"), so the monitor alone
  // cannot see an off-origin URL the shell's own policy refused. Record the refusals too.
  const cspViolations: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error" && /Content Security Policy/i.test(message.text())) cspViolations.push(message.text());
  });
  const failedRequests: string[] = [];
  page.on("requestfailed", (request) => failedRequests.push(request.url()));

  await page.goto("/");
  await expect(page.getByText(fixtureDisclosure)).toBeVisible();
  await expect(page.getByText(/Not a Minnesota or Texas topology/i)).toBeVisible();

  await page.getByRole("button", { name: /Candidate A/i }).first().click();
  await expect(page.getByText(/NETWORK STATE.*CANDIDATE A/i)).toBeVisible();
  await expect(page.getByRole("heading", { name: "Synthetic five-bus fixture" })).toBeVisible();
  await expect(page.locator(".flux-shell__inspector").getByText("Candidate A", { exact: true })).toBeVisible();

  const chat = page.locator(".flux-shell__chat");
  await chat.getByRole("button", { name: "Expand" }).click();
  await expect(chat.getByText("Agent unavailable.")).toBeVisible();
  await expect(chat.getByText(/The static demo does not open a live agent connection/i)).toBeVisible();
  await expect(chat.getByText(/No live tool call was made/i)).toBeVisible();
  await expect(chat.getByText("Source status: Unavailable", { exact: true })).toBeVisible();

  await chat.getByRole("button", { name: "Edit" }).click();
  const geography = chat.getByLabel("Geography");
  await geography.fill("Review-only synthetic context");
  await expect(geography).toHaveValue("Review-only synthetic context");
  await chat.getByRole("button", { name: "Done editing" }).click();
  await expect(chat.getByRole("button", { name: "Edit" })).toBeVisible();
  await expect(chat.getByText("Review-only synthetic context", { exact: true })).toBeVisible();
  await expect(chat.getByText(/revision .*:a:c2/i).first()).toBeVisible();

  await chat.getByRole("button", { name: "Collapse" }).click();
  await chat.getByRole("button", { name: "Expand" }).click();
  await expect(chat.getByText("Review-only synthetic context", { exact: true })).toBeVisible();
  await expect(chat.getByText(/revision .*:a:c2/i).first()).toBeVisible();

  await page.getByRole("button", { name: /Candidate B/i }).first().click();
  await expect(chat.getByText("Review-only synthetic context", { exact: true })).toBeVisible();
  await expect(chat.getByText(/revision .*:b:c3/i).first()).toBeVisible();

  await expect(page.getByText(/Deck overlay: initialized with 0 accepted feature layers/i)).toBeVisible();
  assertNoRequestLeavesTheOrigin(requests, new URL(page.url()).origin);
  expect(cspViolations).toEqual([]);
  expect(failedRequests).toEqual([]);
});

test("the demo is unaffected when every off-origin request is cut", async ({ page }) => {
  // Nothing off-origin may be load-bearing. Aborting all of it must change nothing:
  // the basemap, the overlay, and the fixture all come from this origin.
  const aborted: string[] = [];
  await page.route("**", async (route, request) => {
    if (new URL(request.url()).origin === "http://127.0.0.1:4173") return route.continue();
    aborted.push(request.url());
    return route.abort();
  });
  await page.goto("/");
  await expect(page.getByText(fixtureDisclosure)).toBeVisible();
  await expect(page.getByText(/Deck overlay: initialized with 0 accepted feature layers/i)).toBeVisible();
  await expect(page.locator(".map-foundation-notice")).toContainText(/Offline geometry-free basemap/i);
  await page.getByRole("button", { name: /Candidate A/i }).first().click();
  await expect(page.getByText(/NETWORK STATE.*CANDIDATE A/i)).toBeVisible();
  expect(aborted).toEqual([]);
});

test("an overlay that never initialized is never reported as initialized", async ({ page }) => {
  // Deny the WebGL contexts deck needs. The UI must observe the failure rather
  // than reporting health from a mount effect.
  await page.addInitScript(() => {
    const original = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (this: HTMLCanvasElement, type: string, ...rest: unknown[]) {
      if (type === "webgl" || type === "webgl2" || type === "experimental-webgl") return null;
      return (original as (...args: unknown[]) => unknown).call(this, type, ...rest);
    } as typeof HTMLCanvasElement.prototype.getContext;
  });
  await page.goto("/");
  const notice = page.locator(".map-foundation-notice");
  await expect(notice).toContainText(/Basemap unavailable: .*WebGL2 is required/i);
  // The claim under test: without an initialized overlay the UI must not say it has one.
  // A mount-effect onInitialized reports "initialized with 0 accepted feature layers" here.
  await expect(notice).not.toContainText(/Deck overlay: initialized/i);
  await expect(notice).toContainText(/Deck overlay: (initializing|unavailable \(request_failed\))/i);
  // The rest of the static demo still works while the overlay is down.
  await page.getByRole("button", { name: /Candidate A/i }).first().click();
  await expect(page.getByText(/NETWORK STATE.*CANDIDATE A/i)).toBeVisible();
});

test("keyboard selection and disclosure focus remain usable", async ({ page }) => {
  await page.goto("/");
  const candidate = page.getByRole("button", { name: /Candidate B/i }).first();
  await candidate.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByText(/NETWORK STATE.*CANDIDATE B/i)).toBeVisible();

  const disclosure = page.getByRole("button", { name: "Data, units & limits" });
  await disclosure.click();
  const dialog = page.getByRole("dialog", { name: "Data disclosure" });
  await expect(dialog).toBeVisible();
  await expect(page.getByRole("button", { name: "Close disclosure" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "Close disclosure" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(disclosure).toBeFocused();
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
    await expect(page.getByText(fixtureDisclosure)).toBeVisible();
  });
}
