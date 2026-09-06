import { expect, test, type Page } from "@playwright/test";

const recorded = new WeakMap<Page, string[]>();
const pageErrors = new WeakMap<Page, string[]>();
const hasLiveApi = Boolean(process.env.FLUX_API_ORIGIN);

test.beforeEach(async ({ page }) => {
  const requests: string[] = [];
  recorded.set(page, requests);
  page.on("request", (request) => requests.push(request.url()));
  page.on("requestfailed", (request) => requests.push(request.url()));
  const errors: string[] = [];
  pageErrors.set(page, errors);
  page.on("pageerror", (error) => errors.push(error.message));
});

async function expectSameOriginOnly(page: Page): Promise<void> {
  const origin = new URL(page.url()).origin;
  expect((recorded.get(page) ?? []).filter((url) => new URL(url).origin !== origin)).toEqual([]);
}

async function expectNoPageErrors(page: Page): Promise<void> {
  expect(pageErrors.get(page) ?? []).toEqual([]);
}

test("the primary route keeps a compact source-backed weather strip and named Minnesota boundary", async ({ page }) => {
  await page.goto("/");
  const room = page.getByLabel("Flux control room");
  await expect(room).toBeVisible();
  await expect(room.getByText(/Weather, grid context, and evidence/i)).toBeVisible();
  if (!hasLiveApi) {
    await expect(room.getByText(/Weather unavailable/i)).toBeVisible();
    await expect(page.getByRole("button", { name: "Texas grid model" })).toBeVisible();
    await expectNoPageErrors(page);
    await expectSameOriginOnly(page);
    return;
  }
  await expect(room.getByLabel("Weather timeline").getByRole("listitem")).toHaveCount(12);
  await expect(room.getByText(/of 240/i)).toBeVisible();
  await expect(room.getByText(/synthetic \(ACTIVSg2000\)/i).first()).toBeVisible();
  await expect(room.getByText(/Synthetic Texas cascade playback/i)).toBeVisible();

  await room.getByRole("button", { name: /Minnesota/i }).click();
  await expect(room.getByText(/aggregate \/ topology unavailable/i)).toBeVisible();
  await expect(room.getByText(/Weather unavailable: this scenario supplied no timeline/i)).toBeVisible();
  await expect(page.getByRole("button", { name: "Texas grid model" })).toBeDisabled();
  await expectNoPageErrors(page);
  await expectSameOriginOnly(page);
});

test("Texas model navigation uses only canonical synthetic geometry and carries a prompt context", async ({ page }) => {
  test.skip(!hasLiveApi, "requires the real demo API; static CI verifies named unavailable state instead");
  await page.goto("/");
  await page.getByRole("button", { name: "Texas grid model" }).click();
  const stage = page.getByLabel("Texas grid model scene");
  await expect(stage).toBeVisible();
  await expect(stage.getByText(/synthetic model-ID scene/i)).toBeVisible();
  await expect(page.getByLabel("Navigable synthetic Texas model")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByLabel("Navigable synthetic Texas model").locator("canvas.maplibregl-canvas")).toBeVisible();

  await stage.getByLabel("Component search").fill("line:973");
  await expect(stage.getByText(/Showing 1 matching canonical model IDs/i)).toBeVisible();
  const component = stage.getByLabel("Selected model component");
  await component.selectOption("line:973");
  await stage.getByRole("button", { name: /Open component-failure request/i }).click();
  const dock = page.getByLabel("Copilot chat");
  await expect(dock).toBeVisible();
  await expect(dock.getByLabel("Question for Flux Copilot")).toHaveValue(/line:973/);
  await expect(dock.getByLabel("Scene context")).toContainText(/Texas|uri_2021|line:973/i);
  await expect(dock.getByRole("button", { name: "Send" })).toBeEnabled();
  await dock.getByRole("button", { name: "Send" }).click();
  await expect(dock.getByText("Answer complete", { exact: true })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByLabel("Flux control room").getByText(/Live synthetic Texas cascade/i)).toBeVisible();
  await expect(stage.getByLabel("Live synthetic cascade events")).toBeVisible();
  await expectNoPageErrors(page);
  await expectSameOriginOnly(page);
});

test("the retired five-bus fixture remains an explicit fallback", async ({ page }) => {
  await page.goto("/");
  const legacy = page.getByLabel("Legacy synthetic fixture");
  await expect(legacy.getByText(/Synthetic five-bus comparison/i)).toHaveCount(0);
  await legacy.getByRole("button", { name: /Show legacy synthetic fixture/i }).click();
  await expect(legacy.getByText(/Synthetic five-bus comparison/i)).toBeVisible();
  await expect(legacy.getByText(/not Texas, Minnesota/i)).toBeVisible();
  await expectSameOriginOnly(page);
});

for (const viewport of [
  { name: "desktop", width: 1440, height: 900 },
  { name: "mobile", width: 390, height: 844 },
]) {
  test(`${viewport.name} primary route has no horizontal overflow`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await page.goto("/");
    await expect(page.getByLabel("Flux control room")).toBeVisible();
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
    await expectNoPageErrors(page);
  });
}
