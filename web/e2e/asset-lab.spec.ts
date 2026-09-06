import { expect, test } from "@playwright/test";

test("the published runtime pack exposes a verified same-origin model manifest", async ({ page }) => {
  const requests: string[] = [];
  const failed: string[] = [];
  page.on("request", (request) => requests.push(new URL(request.url()).pathname));
  page.on("requestfailed", (request) => failed.push(`${new URL(request.url()).pathname}: ${request.failure()?.errorText}`));

  const response = await page.goto("/assets/flux-grid/manifest.json");
  expect(response?.ok()).toBe(true);
  expect(failed).toEqual([]);
  const manifest = await response?.json() as { assets?: Array<{ lods?: Record<string, { path?: string }> }> };
  expect(manifest.assets?.some((asset) => Object.values(asset.lods ?? {}).some((lod) => lod.path?.endsWith(".glb")))).toBe(true);
  expect(requests).toContain("/assets/flux-grid/manifest.json");
});
