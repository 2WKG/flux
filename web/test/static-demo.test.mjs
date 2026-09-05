import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("frozen static demo bundles the current fixture without fetching", async () => {
  const [source, app, fixtureText] = await Promise.all([
    readFile(new URL("../src/main.tsx", import.meta.url), "utf8"),
    readFile(new URL("../dist/assets/app.js", import.meta.url), "utf8"),
    readFile(new URL("../../data/demo/bundle.json", import.meta.url), "utf8"),
  ]);
  const fixture = JSON.parse(fixtureText);

  assert.doesNotMatch(source, /\bfetch\s*\(/);
  assert.doesNotMatch(app, /\bfetch\s*\(/);
  assert.ok(app.includes(fixture.fixtureHash));
  assert.ok(app.includes(fixture.execution.provenance.artifactId));
});