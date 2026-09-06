import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

const outputDirectory = mkdtempSync(join(tmpdir(), "flux-inspector-"));
process.on("exit", () => rmSync(outputDirectory, { recursive: true, force: true }));
// Run tsc's entrypoint through this Node binary rather than ./node_modules/.bin/tsc:
// that shim is POSIX-only, so spawning it fails with ENOENT on a Windows checkout.
// inspector.ts imports ./selection.ts, which imports ../scene/minnesota-adapter.ts.
execFileSync(
  process.execPath,
  [
    "./node_modules/typescript/bin/tsc",
    "src/selection/inspector.ts",
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
const { buildInspectorViewModel, hasRenderableDetail } = await import(
  pathToFileURL(join(outputDirectory, "selection", "inspector.js")).href
);
const { selectEntity, clearSelection, reconcileVisibility } = await import(
  pathToFileURL(join(outputDirectory, "selection", "selection.js")).href
);

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

function detailFor(entity) {
  return {
    fields: [{ label: "Voltage class", value: "115 kV" }],
    truthLabel: entity.truthLabel,
    provenance: { sourceNames: entity.provenance.sourceNames, fixtureBatchIds: entity.provenance.fixtureBatchIds },
  };
}

test("no selection renders the empty view model, not an unavailable card", () => {
  const viewModel = buildInspectorViewModel(clearSelection(), () => null);
  assert.equal(viewModel.kind, "empty");
});

test("a selection with source detail renders ready, carrying the pick's label and the looked-up detail", () => {
  const entity = node();
  const state = selectEntity(entity);
  const viewModel = buildInspectorViewModel(state, detailFor);

  assert.equal(viewModel.kind, "ready");
  assert.equal(viewModel.presence, "visible");
  assert.equal(viewModel.entity.truthLabel, "source_backed");
  assert.deepEqual(viewModel.detail.fields, [{ label: "Voltage class", value: "115 kV" }]);
  assert.ok(hasRenderableDetail(viewModel));
});

test("a selection with no source detail renders a named unavailable state, never a blank panel or a zero", () => {
  const state = selectEntity(node());
  const viewModel = buildInspectorViewModel(state, () => null);

  assert.equal(viewModel.kind, "unavailable");
  assert.equal(viewModel.entity.id, "mn-node-1");
  assert.match(viewModel.missingPrerequisite, /No source detail record for node "mn-node-1"/);
  assert.ok(!hasRenderableDetail(viewModel));
  assert.ok(
    !("fields" in viewModel) && !("detail" in viewModel),
    "unavailable must not carry a fields/detail shape a renderer could mistake for data",
  );
});

test("an entity that leaves the visible set still renders ready with not_in_view presence -- selection is not dropped", () => {
  const entity = node();
  const selected = selectEntity(entity);
  const outOfView = reconcileVisibility(selected, new Set(["some-other-node"]));

  const viewModel = buildInspectorViewModel(outOfView, detailFor);
  assert.equal(viewModel.kind, "ready");
  assert.equal(viewModel.presence, "not_in_view");
  assert.equal(viewModel.entity.truthLabel, "source_backed", "label survives navigation unchanged");
});

test("detail lookup receives the exact picked entity, never a re-derived id", () => {
  const entity = node({ kind: "facility", id: "mn-facility-9", truthLabel: "unavailable" });
  const state = selectEntity(entity);
  let received = null;
  buildInspectorViewModel(state, (e) => {
    received = e;
    return null;
  });
  assert.equal(received.id, "mn-facility-9");
  assert.equal(received.kind, "facility");
  assert.equal(received.truthLabel, "unavailable");
});
