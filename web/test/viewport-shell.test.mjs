import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const sourceUrl = new URL("../src/main.tsx", import.meta.url);
const stylesUrl = new URL("../src/styles.css", import.meta.url);

async function shellFiles() {
  return Promise.all([readFile(sourceUrl, "utf8"), readFile(stylesUrl, "utf8")]);
}

test("viewport shell keeps the scene primary and gives its surrounding panels compact states", async () => {
  const [source, styles] = await shellFiles();

  assert.match(source, /className="workspace viewport-shell"/);
  assert.match(source, /className="map scene-viewport"/);
  assert.match(source, /className="timeline compact-panel"/);
  assert.match(source, /className="inspector"/);
  assert.match(styles, /grid-template-columns:\s*minmax\(0, 1fr\) minmax\(280px, 360px\)/);
  assert.match(styles, /min-height:\s*clamp\(500px, 64vh, 700px\)/);
  assert.match(styles, /@media \(max-width: 1180px\)/);
  assert.match(styles, /@media \(max-width: 980px\)/);
});

test("chat dock is collapsed by default and expands to an explicitly unavailable static state", async () => {
  const [source, styles] = await shellFiles();

  assert.match(source, /useState\(false\)/);
  assert.match(source, /aria-expanded=\{chatOpen\}/);
  assert.match(source, /Unavailable in static preview/);
  assert.match(source, /no Copilot endpoint, model result, or Minnesota artifact/);
  assert.match(styles, /\.chat-dock\.collapsed/);
  assert.match(styles, /\.chat-dock\.expanded/);
});
