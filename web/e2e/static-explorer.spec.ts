import { expect, test, type Page } from "@playwright/test";

const SOURCE_BACKED_CLAIM = /source[_ -]?backed|source[_ -]?supported|source[_ -]?screened|Minnesota coverage/i;
const recorded = new WeakMap<Page, string[]>();

const syntheticLayer = {
  type: "FeatureCollection",
  crs: { type: "name", properties: { name: "EPSG:4326" } },
  provenance: {
    source_kinds: ["simulated"],
    topology: "synthetic (ACTIVSg2000)",
    source_names: ["pipelines.activsg"],
    coord_sources: ["ACTIVSg2000.aux (2018 build)"],
    fixture_batch_ids: ["activsg2000@2018"],
  },
  features: [
    { type: "Feature", id: "101", geometry: { type: "Point", coordinates: [-97.5, 30.1] }, properties: { bus_id: "101", name: "Synthetic West", kv: 230, coord_source: "ACTIVSg2000.aux (2018 build)", source_name: "pipelines.activsg", ba_code: "ERCO" } },
    { type: "Feature", id: "102", geometry: { type: "Point", coordinates: [-96.2, 31.3] }, properties: { bus_id: "102", name: "Synthetic East", kv: 500, coord_source: "ACTIVSg2000.aux (2018 build)", source_name: "pipelines.activsg", ba_code: "ERCO" } },
  ],
};

test.beforeEach(async ({ page }) => {
  const requests: string[] = [];
  recorded.set(page, requests);
  page.on("request", (request) => requests.push(request.url()));
});

async function supplySyntheticLayer(page: Page) {
  await page.route("**/layers/buses", (route) => route.fulfill({
    contentType: "application/geo+json",
    body: JSON.stringify(syntheticLayer),
  }));
}

async function expectNoUnsupportedClaims(page: Page) {
  await expect(page.getByText(SOURCE_BACKED_CLAIM)).toHaveCount(0);
  await expect(page.locator("main")).toHaveAttribute("data-source-status", "synthetic");
}

async function expectNoUnexpectedOrigin(page: Page) {
  const origin = new URL(page.url()).origin;
  const unexpected = (recorded.get(page) ?? []).filter((url) => {
    const requestOrigin = new URL(url).origin;
    return requestOrigin !== origin && requestOrigin !== "https://fonts.googleapis.com" && requestOrigin !== "https://fonts.gstatic.com";
  });
  expect(unexpected).toEqual([]);
}

test("the main route renders the API layer as a labelled deck.gl simulation", async ({ page }) => {
  await supplySyntheticLayer(page);
  await page.goto("/");

  await expect(page.getByRole("heading", { name: /Inspect the grid simulation scene/i })).toBeVisible();
  const scene = page.getByLabel("Deck.gl grid simulation");
  await expect(scene).toBeVisible();
  await expect(scene.getByText(/deck\.gl simulation scene · Synthetic/i)).toBeVisible();
  await expect(scene.getByText(/2 server-supplied ACTIVSg2000 buses/i)).toBeVisible();
  await expect(scene.locator("canvas")).toHaveCount(1);
  await expectNoUnsupportedClaims(page);
  await expectNoUnexpectedOrigin(page);
});

test("a missing layer response shows the explicit five-bus fallback", async ({ page }) => {
  await page.goto("/");

  const fallback = page.getByLabel("Offline five-bus fallback");
  await expect(fallback).toBeVisible();
  await expect(fallback.getByText(/OFFLINE FALLBACK · SYNTHETIC FIVE-BUS FIXTURE/i)).toBeVisible();
  await expect(fallback.getByText(/not Texas, Minnesota, ERCOT, MISO, or an interconnection result/i)).toBeVisible();
  await expect(page.locator("main")).toHaveAttribute("data-source-status", "unavailable");
  await expect(page.getByText(SOURCE_BACKED_CLAIM)).toHaveCount(0);
});

test("the chat dock names its unavailable state without offering an answer", async ({ page }) => {
  await supplySyntheticLayer(page);
  await page.goto("/");
  const dock = page.locator("section.chat-dock");
  await expect(dock).toHaveClass(/collapsed/);
  await dock.getByRole("button", { name: /Ask about visible evidence/i }).click();
  await expect(dock).toHaveClass(/expanded/);
  await expect(dock.getByText(/no Copilot endpoint, model result, or Minnesota artifact to query/i)).toBeVisible();
});

test("navigation preserves the URL and returns to the primary scene", async ({ page }) => {
  await supplySyntheticLayer(page);
  await page.goto("/explainer?scenario=uri_2021&h=3#method");
  await expect(page.getByRole("heading", { name: /How the math works/i })).toBeVisible();

  await page.getByRole("link", { name: "Scenario explorer" }).click();
  await expect(page).toHaveURL(/\/?scenario=uri_2021&h=3#method$/);
  await expect(page.getByLabel("Deck.gl grid simulation")).toBeVisible();
  await expectNoUnsupportedClaims(page);
});
