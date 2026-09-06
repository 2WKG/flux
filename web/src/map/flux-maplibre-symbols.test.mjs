import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp, rm, writeFile} from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';

// The module is a MapLibre style-spec builder with no runtime import yet, so it
// is compiled and exercised here rather than shipped as untyped, unread code.
const compiled = await build({entryPoints: [new URL('./layers/fluxMapLibreSymbols.ts', import.meta.url).pathname], bundle: true, packages: 'external', platform: 'node', format: 'esm', write: false});
const folder = await mkdtemp(new URL('../../node_modules/.flux-symbols-test-', import.meta.url).pathname);
const entry = path.join(folder, 'symbols.mjs');
await writeFile(entry, compiled.outputFiles[0].text);
const {createFluxMapLibreSymbolLayer} = await import(pathToFileURL(entry).href);
test.after(() => rm(folder, {recursive: true, force: true}));

test('the badge layer is regional only and never renders an unavailable or failed placement', () => {
  const layer = createFluxMapLibreSymbolLayer('flux-placements');
  assert.equal(layer.source, 'flux-placements');
  assert.equal(layer.id, 'flux-category-symbols');
  assert.equal(layer.maxzoom, 15);
  const [, , allowed] = layer.filter;
  assert.deepEqual(allowed[1], ['source_supported', 'source_screened', 'hypothetical', 'synthetic']);
  for (const withheld of ['unavailable', 'request_failed']) {
    assert.ok(!allowed[1].includes(withheld), `${withheld} must not draw a badge`);
  }
});

test('the icon is keyed by the accepted archetype id and carries no status colour', () => {
  const layer = createFluxMapLibreSymbolLayer('flux-placements', 'custom-id');
  assert.equal(layer.id, 'custom-id');
  assert.deepEqual(layer.layout['icon-image'], ['concat', 'flux-grid:', ['get', 'archetype_id']]);
  assert.equal(JSON.stringify(layer).includes('icon-color'), false);
  assert.equal(layer.layout['icon-pitch-alignment'], 'viewport');
});
