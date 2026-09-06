/**
 * The one stylesheet.
 *
 * `viewport-shell.test.mjs` already proves that no class reaches the DOM
 * without *a* rule. It cannot prove that the rule does anything: an empty
 * declaration block for every adopted class satisfies it completely, which is
 * the exact failure mode the four-sheets-into-one merge could have produced.
 * This file closes that hole, and pins the two other properties the merge
 * carries: one physical file, and no font family the page does not load.
 */
import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const webRoot = fileURLToPath(new URL("../", import.meta.url));
const styles = await readFile(path.join(webRoot, "src/styles.css"), "utf8");
const withoutComments = styles.replace(/\/\*[\s\S]*?\*\//g, "");

/**
 * `{selector, declarations, context}` for every top-level and nested rule.
 *
 * `context` is the chain of enclosing at-rule preludes (`@media (max-width:
 * 1180px)`, and so on), empty for a rule that applies unconditionally. The
 * empty-block check below needs it: a class whose only surviving declaration
 * sits inside a `@media` block has no baseline appearance at all, which is the
 * failure this file exists to catch.
 */
function parseRules(css) {
  const rules = [];
  const walk = (body, context) => {
    let index = 0;
    while (index < body.length) {
      const open = body.indexOf("{", index);
      if (open === -1) break;
      let depth = 1;
      let close = open + 1;
      while (close < body.length && depth > 0) {
        if (body[close] === "{") depth += 1;
        else if (body[close] === "}") depth -= 1;
        close += 1;
      }
      const prelude = body.slice(index, open).trim();
      const inner = body.slice(open + 1, close - 1);
      if (prelude.startsWith("@") && inner.includes("{")) walk(inner, context ? `${context} ${prelude}` : prelude);
      else if (!prelude.startsWith("@")) {
        const declarations = inner.split(";").map((entry) => entry.trim()).filter(Boolean);
        for (const selector of prelude.split(",")) rules.push({ selector: selector.trim(), declarations, context });
      }
      index = close;
    }
  };
  walk(css, "");
  return rules;
}

const rules = parseRules(withoutComments);

/**
 * One representative class from each adopted sheet's own namespace, plus the
 * three components that shipped with no stylesheet at all. Every one of these
 * must own at least one real declaration.
 */
const ADOPTED_CLASSES = [
  // chat/chat.css
  "flux-chat", "flux-chat-header", "flux-chat-state", "flux-chat-context", "flux-chat-fields",
  "flux-chat-notice", "flux-chat-transcript", "flux-chat-message", "flux-chat-compose", "flux-chat-empty",
  "state-streaming", "state-error", "state-done", "state-cancelled", "role-user",
  // ask/results/result-cards.css
  "ask-results", "ask-result", "ask-result__eyebrow", "ask-result__answer", "ask-result__status",
  "ask-result__citations", "ask-result__provenance", "ask-result__caveat", "ask-result__empty",
  "ask-result__fixture-marker", "ask-result__unverified-number", "ask-result__number",
  "is-verified", "is-unavailable", "is-failed", "is-fixture",
  // layers/layer-controls.css
  "layer-controls", "layer-list", "layer-row", "layer-main", "layer-category", "layer-status",
  "layer-evidence-class", "layer-reason", "layer-refusal", "layer-note", "layer-details", "layer-evidence",
  // renderer/renderer.css
  "map-foundation", "map-foundation-notice", "grid-map", "grid-map-note", "grid-controls",
  "grid-coverage", "grid-results", "grid-inventory",
  // The three components that carried no sheet at all (spec §A.4).
  "asset-inspector", "run-trace", "failure-state",
];

/**
 * The class's *own* rule: the one whose subject -- the last compound in the
 * selector -- carries the class. `.flux-chat-header p` styles a paragraph, not
 * the header, so it does not count. Without this the check has no teeth:
 * emptying `.flux-chat-header` while a descendant rule survives passes.
 */
function ownRules(name) {
  const pattern = new RegExp(`\\.${name}(?![A-Za-z0-9_-])`);
  return rules.filter((rule) => {
    const subject = rule.selector.split(/[\s>+~]+/).filter(Boolean).pop() ?? "";
    return pattern.test(subject);
  });
}

test("every adopted class owns at least one real declaration, not an empty block", () => {
  // Outside any at-rule. A responsive `@media` override is not a visual system:
  // `.layer-controls`'s primary rule could be emptied to `{ }` and the class
  // would still have owned a declaration through `@media (max-width: 1180px)`,
  // which is precisely the merge failure this file is here to catch.
  const empty = ADOPTED_CLASSES.filter((name) => {
    const owned = ownRules(name).filter((rule) => rule.context === "");
    return owned.length === 0 || owned.every((rule) => rule.declarations.length === 0);
  });
  assert.deepEqual(empty, [], `adopted classes with no unconditional declaration of their own: ${empty.join(", ")}`);
});

test("the empty-block check is scoped to unconditional rules", () => {
  // The check's own teeth, proved on a sheet rather than asserted in prose: a
  // class declared only inside `@media` must not satisfy it.
  const onlyInMedia = parseRules(".probe { }\n@media (max-width: 100px) { .probe { padding: 1rem } }");
  const unconditional = onlyInMedia.filter((rule) => rule.selector === ".probe" && rule.context === "");
  assert.equal(onlyInMedia.length, 2, "both rules parse");
  assert.equal(unconditional.length, 1, "the primary rule is the only unconditional one");
  assert.deepEqual(unconditional[0].declarations, [], "and it is empty, so the class fails the check");
  assert.equal(onlyInMedia.find((rule) => rule.context !== "")?.context, "@media (max-width: 100px)");
});

test("the unified sheet is one physical file; the four component sheets are gone", async () => {
  const found = [];
  const walk = async (dir) => {
    for (const entry of await readdir(dir, { withFileTypes: true })) {
      const file = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        if (!["node_modules", "dist"].includes(entry.name)) await walk(file);
      } else if (path.extname(entry.name) === ".css") {
        found.push(path.relative(webRoot, file));
      }
    }
  };
  await walk(path.join(webRoot, "src"));
  assert.deepEqual(found.sort(), ["src/styles.css"], "a component stylesheet exists beside src/styles.css again");
});

test("the sheet declares no font family it does not load, and fetches nothing off-origin", () => {
  // No `@import url(https://…)` and no `@font-face`: after the webfonts were
  // dropped the page loads no font resource at all, so any family it names must
  // be one the platform already has.
  assert.doesNotMatch(withoutComments, /@font-face/);
  assert.deepEqual([...withoutComments.matchAll(/@import[^;]*https?:\/\/[^;]*/g)].map((match) => match[0]), []);
  assert.deepEqual([...withoutComments.matchAll(/url\(\s*['"]?https?:\/\//g)].map((match) => match[0]), []);

  // The one @import that remains is a local package file, inlined at build time.
  const imports = [...withoutComments.matchAll(/@import\s+([^;]+);/g)].map((match) => match[1].trim());
  assert.deepEqual(imports, ['"maplibre-gl/dist/maplibre-gl.css"']);
  // CSS only allows @import before any rule, so it must still be first.
  assert.ok(withoutComments.indexOf("@import") < withoutComments.indexOf("{"), "@import must precede every rule");

  // Every family named anywhere in the sheet, from `font-family` and the `font`
  // shorthand and the two typography tokens.
  const named = new Set();
  for (const match of withoutComments.matchAll(/(?:font-family|font|--font-sans|--font-mono)\s*:\s*([^;}]+)/g)) {
    for (const family of match[1].split(",")) {
      const cleaned = family.trim().replace(/^['"]|['"]$/g, "");
      // Drop the non-family parts of the `font` shorthand (weight, size, line-height).
      if (cleaned === "" || /^(?:\d|\.|inherit$|initial$|unset$)/.test(cleaned)) continue;
      named.add(cleaned.replace(/^\d[^ ]*\s+/, "").trim());
    }
  }
  const generic = new Set([
    "ui-sans-serif", "ui-monospace", "system-ui", "-apple-system", "BlinkMacSystemFont",
    "sans-serif", "serif", "monospace", "cursive", "inherit", "var(--font-sans)", "var(--font-mono)",
  ]);
  const unloadable = [...named].filter((family) => !generic.has(family) && !family.startsWith("var(--font-"));
  assert.deepEqual(unloadable, [], `the sheet names ${unloadable.join(", ")} but loads no font file for it`);
});

test("the typography tokens are the stack the repo's own visual guide names", () => {
  // docs/design/texas-workspace-prototype.html:9 (sans) and :17 (mono).
  assert.match(styles, /--font-sans:\s*ui-sans-serif,\s*system-ui,\s*sans-serif/);
  assert.match(styles, /--font-mono:\s*ui-monospace,\s*monospace/);
  assert.doesNotMatch(styles, /Manrope/);
  assert.doesNotMatch(styles, /DM Mono/);
});

test("the rival panel, border, ink and state colours collapsed onto the :root tokens", () => {
  // The exact hexes the four sheets carried for one role each. Their survival
  // anywhere in the sheet means a component kept its own visual system.
  const retired = [
    // `#0a1c2c` is deliberately absent: the shell's own SVG readout fill uses it
    // for a different role and predates the merge.
    "#111b2d", "#102033", // two rival panel backgrounds
    "#294c65", "#3a5276", "#49617d", // three rival panel borders
    "#eaf6ff", "#eaf2ff", "#e8eff8", // three rival inks
    "#e8b45c", // the rival amber; `#e1ad55` survives as the single `--amber` token
    "#ed7065", // the rival red; `#ed6d67` survives as the single `--red` token
  ];
  const survivors = retired.filter((hex) => withoutComments.toLowerCase().includes(hex.toLowerCase()));
  assert.deepEqual(survivors, [], `retired component colours still in the sheet: ${survivors.join(", ")}`);
});
