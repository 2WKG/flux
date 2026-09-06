import { expect, test } from "@playwright/test";

const fixtureDisclosure = /Synthetic five-bus fixture.*OpenFreeMap basemap context.*no API required/i;
const openFreeMapHost = "tiles.openfreemap.org";

function assertBoundedRequest(requests: readonly { url: string; method: string }[], baseURL: string) {
  for (const request of requests) {
    expect(request.method).toBe("GET");
    const url = new URL(request.url);
    if (url.origin === baseURL) {
      expect(url.pathname === "/" || url.pathname === "/favicon.ico" || url.pathname.startsWith("/assets/")).toBeTruthy();
      continue;
    }
    expect(url.hostname).toBe(openFreeMapHost);
    expect(url.pathname).toMatch(/^\/(?:styles\/|planet(?:\/|$)|fonts\/|sprites\/)/);
  }
}

test("static explorer supports scenario selection, inspection, and honest unavailable agent state", async ({ page }) => {
  const requests: { url: string; method: string }[] = [];
  page.on("request", (request) => requests.push({ url: request.url(), method: request.method() }));

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

  await expect(page.getByText(/Deck overlay: initialized with zero accepted feature layers/i)).toBeVisible();
  assertBoundedRequest(requests, new URL(page.url()).origin);
});

test("basemap failure is visible while the synthetic fixture remains usable", async ({ page }) => {
  await page.route("https://tiles.openfreemap.org/**", (route) => route.abort());
  await page.goto("/");
  await expect(page.getByText(/Basemap unavailable:/i)).toBeVisible();
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
