import { createHash } from "node:crypto";
import { expect, test } from "@playwright/test";

function glb() {
  const json = Buffer.from(JSON.stringify({ asset: { version: "2.0" }, materials: [{ name: "MAT_STATUS" }] }));
  const padded = Math.ceil(json.length / 4) * 4;
  const bytes = Buffer.alloc(20 + padded + 12, 32);
  bytes.writeUInt32LE(0x46546c67, 0); bytes.writeUInt32LE(2, 4); bytes.writeUInt32LE(bytes.length, 8);
  bytes.writeUInt32LE(padded, 12); bytes.writeUInt32LE(0x4e4f534a, 16); json.copy(bytes, 20);
  bytes.writeUInt32LE(4, 20 + padded); bytes.writeUInt32LE(0x004e4942, 24 + padded); bytes.set([1, 2, 3, 4], 28 + padded);
  return bytes;
}

/** A real MapLibre control must cross the LOD boundary and request a verified GLB. */
test("Texas map zoom control reaches lod2 and requests the visible model", async ({ page }) => {
  const model = glb();
  const digest = createHash("sha256").update(model).digest("hex");
  const file = { path: "models/transmission_line_segment.glb", bytes: model.length, sha256: digest, triangles: 12 };
  const glbRequests: string[] = [];
  await page.route("**/demo/model", (route) => route.fulfill({ json: { status: "available", data: { topology: { label: "synthetic (ACTIVSg2000)" }, counts: { buses: 2, branches: 1 }, elements: [
    { element_id: "bus:1", resolved: true, role: "bus", geometry: { type: "Point", coordinates: [-100, 30] } },
    { element_id: "bus:2", resolved: true, role: "bus", geometry: { type: "Point", coordinates: [-98, 32] } },
    { element_id: "line:1", resolved: true, role: "line", geometry: { type: "LineString", coordinates: [[-100, 30], [-98, 32]] } },
  ] } } }));
  await page.route("**/assets/flux-grid/manifest.json", (route) => route.fulfill({ json: { contract_id: "flux:3d-asset-archetypes:v1", assets: [{ archetype_id: "transmission_line_segment", lods: { lod0: file, lod1: file, lod2: file } }] } }));
  await page.route("**/api/v1/grid/asset-placements**", (route) => route.fulfill({ json: { items: [{ id: "placement:1", archetype_id: "transmission_line_segment", position: [-99, 31, 0], label: "Verified placement", artifact_id: "artifact:1", status: "source_supported", visual_mapping: "source_kind" }] } }));
  await page.route("**/assets/flux-grid/models/transmission_line_segment.glb", (route) => { glbRequests.push(route.request().url()); return route.fulfill({ body: model, contentType: "model/gltf-binary" }); });

  await page.goto("/");
  const map = page.getByLabel("Full synthetic Texas topology");
  await expect(map).toBeVisible();
  const zoomIn = map.locator(".maplibregl-ctrl-zoom-in");
  await expect(zoomIn).toBeVisible();
  for (let index = 0; index < 7; index += 1) {
    await zoomIn.click();
    await page.waitForTimeout(300);
  }
  await expect.poll(async () => Number(await map.getAttribute("data-map-zoom"))).toBeGreaterThanOrEqual(12);
  await expect(map).toHaveAttribute("data-visual-lod", "lod2");
  await expect.poll(() => glbRequests.length).toBeGreaterThan(0);
});
