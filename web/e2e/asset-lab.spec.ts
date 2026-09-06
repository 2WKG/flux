import { expect, test } from "@playwright/test";

/** A static-only origin must name the unavailable runtime pack rather than serving an invented manifest. */
test("the asset-pack route names its unavailable upstream without an API origin", async ({ page }) => {
  const response = await page.goto("/assets/flux-grid/manifest.json");
  expect(response?.status()).toBe(503);
  const envelope = await response?.json() as { status?: string; error?: { details?: { reason?: string } } };
  expect(envelope.status).toBe("unavailable");
  expect(envelope.error?.details?.reason).toBe("no_api_origin_configured");
});
