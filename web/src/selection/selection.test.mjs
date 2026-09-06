import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

const outputDirectory = mkdtempSync(join(tmpdir(), "flux-selection-"));
process.on("exit", () => rmSync(outputDirectory, { recursive: true, force: true }));
// Run tsc's entrypoint through this Node binary rather than ./node_modules/.bin/tsc:
// that shim is POSIX-only, so spawning it fails with ENOENT on a Windows checkout.
// selection.ts imports ../scene/minnesota-adapter.ts, so it is compiled alongside it.
execFileSync(
  process.execPath,
  [
    "./node_modules/typescript/bin/tsc",
    "src/selection/selection.ts",
    "src/scene/minnesota-adapter.ts",
    "--target",
    "ES2022",
    "--module",
    "NodeNext",
    "--moduleResolution",
    "NodeNext",
    "--outDir",
    outputDirectory,
  ],
  { cwd: new URL("../..", import.meta.url), stdio: "inherit" },
);
const {
  createSelectionStore,
  reconcileVisibility,
  selectEntity,
  clearSelection,
  toPickedEntity,
} = await import(pathToFileURL(join(outputDirectory, "selection", "selection.js")).href);

function node(overrides = {}) {
  return {
    kind: "node",
    id: "mn-node-1",
    name: "Hennepin Substation",
    truthLabel: "source_backed",
    provenance: { layer: "buses", sourceNames: ["mn_accepted"], fixtureBatchIds: ["batch-1"] },
    ...overrides,
  };
}

test("selecting a picked entity produces a visible selection keyed by the server id", () => {
  const entity = node();
  const state = selectEntity(entity);
  assert.equal(state.kind, "selected");
  assert.equal(state.entity.id, "mn-node-1");
  assert.equal(state.presence, "visible");
  assert.equal(state.entity.truthLabel, "source_backed");
});

test("selection survives navigation: reconciling against a visible set that still contains the id changes nothing", () => {
  const selected = selectEntity(node());
  const stillVisible = reconcileVisibility(selected, new Set(["mn-node-1", "mn-node-2"]));
  assert.equal(stillVisible.kind, "selected");
  assert.equal(stillVisible.presence, "visible");
  assert.equal(stillVisible, selected, "no new state object when nothing changed");
});

test("an entity that disappears from the visible set resolves to a named not_in_view state, never a silent clear", () => {
  const selected = selectEntity(node());
  const afterZoom = reconcileVisibility(selected, new Set(["some-other-node"]));
  assert.equal(afterZoom.kind, "selected", "still selected -- not cleared");
  assert.equal(afterZoom.presence, "not_in_view");
  assert.deepEqual(afterZoom.entity, selected.entity, "label and provenance travel through unchanged");

  const backInView = reconcileVisibility(afterZoom, new Set(["mn-node-1"]));
  assert.equal(backInView.presence, "visible", "reappearing restores visible presence");
});

test("reconciling with no selection is a no-op", () => {
  const empty = clearSelection();
  assert.equal(reconcileVisibility(empty, new Set(["mn-node-1"])), empty);
});

test("clear() is the only path back to no selection", () => {
  assert.deepEqual(clearSelection(), { kind: "none" });
});

test("a store links selection across every reader: one call, every subscriber agrees", () => {
  const store = createSelectionStore();
  const seen = [];
  const unsubscribe = store.subscribe((state) => seen.push(state));

  store.select(node());
  assert.equal(store.getState().kind, "selected");
  assert.equal(seen.length, 1);

  store.reconcileVisibility(new Set(["mn-node-1"]));
  assert.equal(seen.length, 1, "no notification when presence does not change");

  store.reconcileVisibility(new Set());
  assert.equal(store.getState().presence, "not_in_view");
  assert.equal(seen.length, 2);

  unsubscribe();
  store.clear();
  assert.equal(seen.length, 2, "unsubscribed listener receives nothing further");
  assert.equal(store.getState().kind, "none");
});

test("a pick with a valid kind/id/truth label is accepted", () => {
  const result = toPickedEntity(node());
  assert.equal(result.kind, "node");
  assert.equal(result.id, "mn-node-1");
});

test("a pick missing a valid truth label is refused, never given a default", () => {
  for (const raw of [
    node({ truthLabel: undefined }),
    node({ truthLabel: "illustrative" }),
    node({ truthLabel: "" }),
  ]) {
    const result = toPickedEntity(raw);
    assert.equal(result.kind, "rejected", JSON.stringify(raw));
    assert.equal(result.reason, "missing_truth_label");
  }
});

test("a pick with no server id, or an unsupported kind, is refused by name", () => {
  assert.equal(toPickedEntity(node({ id: undefined })).reason, "missing_id");
  assert.equal(toPickedEntity(node({ id: "" })).reason, "missing_id");
  assert.equal(toPickedEntity(node({ kind: "bus" })).reason, "invalid_kind");
  assert.equal(toPickedEntity(null).reason, "malformed_pick");
  assert.equal(toPickedEntity("mn-node-1").reason, "malformed_pick");
});

test("store.pick() only mutates state on a successful validation", () => {
  const store = createSelectionStore();
  const rejection = store.pick(node({ truthLabel: "guessed" }));
  assert.equal(rejection.kind, "rejected");
  assert.equal(store.getState().kind, "none", "rejected pick never becomes a selection");

  const state = store.pick(node());
  assert.equal(state.kind, "selected");
});

test("line and facility kinds round-trip the same way as node", () => {
  for (const kind of ["line", "facility"]) {
    const entity = node({ kind, id: `${kind}-1` });
    const result = toPickedEntity(entity);
    assert.equal(result.kind, kind);
    assert.equal(result.id, `${kind}-1`);
  }
});
