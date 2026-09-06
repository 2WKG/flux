// 2WKG-274: the Cloudflare edge and this origin's same-origin forward are two
// programs that publish paths, and cloudflared evaluates its rule *before* the
// static rule, so anything the edge admits bypasses `server.mjs` entirely. If the
// two lists disagree, the wider one is the real public API surface and nobody
// reviewed it. `PROXIED` in `web/server.mjs` is the single definition; the tunnel
// config carries the derived string. These tests fail when either side drifts.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { INGRESS_PATH_PATTERN, PROXIED } from "../server.mjs";

const configPath = new URL("../../deploy/cloudflared/config.example.yml", import.meta.url);

async function ingressPathFromConfig() {
  const text = await readFile(configPath, "utf8");
  const lines = text.split(/\r?\n/).filter((line) => /^\s*path:\s*\S/.test(line));
  assert.equal(lines.length, 1, "the tunnel config must declare exactly one path rule");
  return lines[0].replace(/^\s*path:\s*/, "").trim();
}

test("the tunnel config publishes exactly the derived allowlist", async () => {
  assert.equal(await ingressPathFromConfig(), INGRESS_PATH_PATTERN);
});

test("every path the edge admits is a path this origin forwards, and vice versa", async () => {
  const edge = new RegExp(await ingressPathFromConfig());
  const admitted = [
    "/health",
    "/layers/mn",
    "/api/v1/grid/layers/mn",
    "/api/v1/grid/asset-placements",
    "/assets/flux-grid/manifest.json",
    "/demo/model",
    "/scenarios",
    "/scenarios/heat-wave",
  ];
  for (const pathname of admitted) {
    assert.ok(edge.test(pathname), `the edge must admit ${pathname}`);
    assert.ok(
      PROXIED.some((entry) => entry.pattern.test(pathname) && entry.methods.includes("GET")),
      `${pathname} is admitted by the edge but not forwarded by server.mjs`,
    );
  }

  // The four paths the old ingress rule published beyond the forward's allowlist,
  // plus the POST surface the edge must never expose (cloudflared filters paths,
  // not methods, so a `/ask` rule would publish the Copilot ask endpoint).
  for (const pathname of ["/lines/top", "/elements/critical", "/predictions", "/cascade", "/ask"]) {
    assert.ok(!edge.test(pathname), `the edge must not publish ${pathname}`);
  }

  // Nothing in the forward's GET table may be missing from the edge.
  for (const entry of PROXIED) {
    if (!entry.methods.includes("GET")) {
      assert.equal(entry.ingress, undefined, "a non-GET entry must not carry an ingress fragment");
      continue;
    }
    assert.ok(entry.ingress, "every GET entry needs an ingress fragment");
    assert.ok(
      INGRESS_PATH_PATTERN.includes(entry.ingress),
      `${entry.ingress} is forwarded by server.mjs but absent from the derived ingress pattern`,
    );
  }
});
