import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

const outputDirectory = mkdtempSync(join(tmpdir(), "flux-nav-search-"));
process.on("exit", () => rmSync(outputDirectory, { recursive: true, force: true }));
execFileSync(
  process.execPath,
  [
    "./node_modules/typescript/bin/tsc",
    "src/navigation/scale-ladder.ts",
    "src/navigation/search.ts",
    "--target", "ES2022", "--module", "NodeNext", "--moduleResolution", "NodeNext", "--outDir", outputDirectory,
  ],
  { cwd: new URL("../..", import.meta.url), stdio: "inherit" },
);
const { search } = await import(pathToFileURL(join(outputDirectory, "search.js")).href);

const provenance = { sourceId: "mn_accepted", artifactId: "mn:facility_capacity:county:2024", truthLabel: "source_backed" };

function candidate(overrides = {}) {
  return {
    id: "c-1",
    name: "Hennepin County",
    scale: "region",
    recordType: "county",
    locationText: "Hennepin",
    provenance,
    ...overrides,
  };
}

test("a matching candidate with valid provenance is returned, carrying that provenance verbatim", () => {
  const outcome = search([candidate()], { text: "hennepin" });
  assert.equal(outcome.results.length, 1);
  assert.deepEqual(outcome.results[0], {
    id: "c-1",
    name: "Hennepin County",
    scale: "region",
    recordType: "county",
    locationText: "Hennepin",
    provenance,
  });
  assert.deepEqual(outcome.excluded, []);
});

test("search matches case-insensitively against name and location text", () => {
  assert.equal(search([candidate()], { text: "HENNEPIN" }).results.length, 1);
  assert.equal(search([candidate({ name: "Some Facility", locationText: "Ramsey" })], { text: "ramsey" }).results.length, 1);
  assert.equal(search([candidate()], { text: "no-such-term" }).results.length, 0);
});

test("empty query text matches every candidate", () => {
  const outcome = search([candidate({ id: "a" }), candidate({ id: "b" })], { text: "   " });
  assert.equal(outcome.results.length, 2);
});

test("recordType and scale filters are exact-match", () => {
  const candidates = [candidate({ id: "county", recordType: "county", scale: "region" }), candidate({ id: "facility", recordType: "facility", scale: "facility" })];
  assert.deepEqual(search(candidates, { text: "", recordType: "facility" }).results.map((r) => r.id), ["facility"]);
  assert.deepEqual(search(candidates, { text: "", scale: "region" }).results.map((r) => r.id), ["county"]);
});

test("a matching candidate with no provenance is never returned as a result -- it is named and excluded", () => {
  const outcome = search([candidate({ provenance: null })], { text: "hennepin" });
  assert.deepEqual(outcome.results, []);
  assert.equal(outcome.excluded.length, 1);
  assert.equal(outcome.excluded[0].id, "c-1");
  assert.equal(outcome.excluded[0].reason, "missing_provenance");
});

test("a candidate with a malformed or invented truth label is treated as having no provenance", () => {
  for (const badProvenance of [
    { sourceId: "", artifactId: "x", truthLabel: "source_backed" },
    { sourceId: "x", artifactId: "", truthLabel: "source_backed" },
    { sourceId: "x", artifactId: "y", truthLabel: "illustrative" },
  ]) {
    const outcome = search([candidate({ provenance: badProvenance })], { text: "hennepin" });
    assert.deepEqual(outcome.results, [], JSON.stringify(badProvenance));
    assert.equal(outcome.excluded[0].reason, "missing_provenance", JSON.stringify(badProvenance));
  }
});

test("a non-matching candidate is neither returned nor excluded -- it simply did not match", () => {
  const outcome = search([candidate({ provenance: null })], { text: "no-such-term" });
  assert.deepEqual(outcome.results, []);
  assert.deepEqual(outcome.excluded, []);
});
