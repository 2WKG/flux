import { expect, test } from "@playwright/test";

test("the Asset Lab loads a verified same-origin model from the published runtime pack", async ({ page }) => {
  const requests: string[] = [];
  const failed: string[] = [];
  page.on("request", (request) => requests.push(new URL(request.url()).pathname));
  page.on("requestfailed", (request) => failed.push(`${new URL(request.url()).pathname}: ${request.failure()?.errorText}`));

  await page.goto("/asset-lab/");
  await expect(page.getByRole("heading", { name: /Infrastructure, made visible/i })).toBeVisible();
  await page.waitForTimeout(2_000);
  expect(failed).toEqual([]);
  const state = await page.evaluate(() => {
    const preview = (window as unknown as { fluxAssetPreview?: { ready?: boolean; loaded?: boolean; errors?: string[] } }).fluxAssetPreview;
    return { ready: preview?.ready, loaded: preview?.loaded, errors: preview?.errors };
  });
  expect(state.errors).toEqual([]);
  expect(state.ready && state.loaded).toBe(true);

  await expect(page.locator("#status-message")).toContainText(/Neutral geometry|Sample token/);
  expect(failed).toEqual([]);

  expect(requests).toContain("/assets/flux-grid/manifest.json");
  expect(requests.some((path) => path.endsWith(".glb"))).toBe(true);
});
