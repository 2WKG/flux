/**
 * The Minnesota control room's accessibility claims, asserted on rules rather
 * than on file bytes.
 *
 * The first version of this file `readFile`d the stylesheet and regexed the
 * string, which proves a substring exists somewhere in a file -- a claim that
 * survives wrapping the entire `prefers-reduced-motion` and `forced-colors`
 * payload in `/* *\/`. Every assertion here is made against a parsed rule tree
 * (comments stripped first, so a commented-out rule simply does not exist) and,
 * for the wire claim, against the built `dist/assets/app.css` that actually
 * ships.
 */
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { fileURLToPath } from "node:url";

const webRoot = new URL("../../", import.meta.url);
const readCss = async (relative) =>
  (await readFile(fileURLToPath(new URL(relative, webRoot)), "utf8")).replace(/\/\*[\s\S]*?\*\//g, "");

/** `{selector, declarations, context}` for every rule, with the enclosing at-rule preludes. */
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

const source = await readCss("src/styles.css");
const rules = parseRules(source);
const minnesota = rules.filter((rule) => rule.selector.includes(".minnesota-control-room"));

/** Every declaration of `property` on a Minnesota selector inside `context`. */
function declared(property, context = "") {
  const values = [];
  for (const rule of minnesota) {
    if (rule.context !== context) continue;
    for (const declaration of rule.declarations) {
      const [name, ...rest] = declaration.split(":");
      if (name.trim() === property) values.push(rest.join(":").trim());
    }
  }
  return values;
}

test("the control room has a high-visibility focus ring and never removes the native one", () => {
  const focus = minnesota.filter((rule) => rule.selector.endsWith(":focus-visible") && rule.context === "");
  assert.equal(focus.length, 1, "there is no unconditional :focus-visible rule for the control room");
  assert.deepEqual(focus[0].declarations, [
    "outline: .25rem solid var(--mn-focus)",
    // The ring's 3:1 contrast depends on this offset keeping it off the button's
    // own --mn-accent fill (1.11:1 against it); the box-shadow separates it from
    // the fill on the inside. Changing either is a contrast change.
    "outline-offset: .25rem",
    "box-shadow: 0 0 0 .125rem #07111d",
  ]);
  const suppressed = minnesota
    .filter((rule) => rule.declarations.some((entry) => /^outline\s*:\s*none/.test(entry)))
    .map((rule) => rule.selector);
  assert.deepEqual(suppressed, [], `these Minnesota rules remove the outline: ${suppressed.join(", ")}`);
  // Forced-colors mode gets a system colour, not a hex the OS theme cannot honour.
  assert.deepEqual(declared("outline-color", "@media (forced-colors: active)"), ["Highlight"]);
});

test("the disabled control is announced and looks disabled rather than merely dimmed", () => {
  const disabled = minnesota.filter(
    (rule) => rule.context === "" && /button(?::disabled|\[aria-disabled="true"\])$/.test(rule.selector),
  );
  assert.equal(disabled.length, 2, "both the :disabled and [aria-disabled] selectors must carry the rule");
  for (const rule of disabled) {
    assert.ok(rule.declarations.includes("cursor: not-allowed"), `${rule.selector} has no not-allowed cursor`);
    // Opacity dimming is what makes a disabled control fail contrast; the rule
    // states its own colours instead.
    assert.ok(rule.declarations.includes("opacity: 1"), `${rule.selector} dims instead of restating its colours`);
  }
});

test("reduced motion and forced colors are real at-rules, not text in a file", () => {
  const reduced = "@media (prefers-reduced-motion: reduce)";
  assert.ok(
    minnesota.some((rule) => rule.context === reduced),
    "no Minnesota rule exists inside the reduced-motion query",
  );
  assert.deepEqual(new Set(declared("animation-duration", reduced)), new Set([".01ms !important"]));
  assert.deepEqual(new Set(declared("transition-duration", reduced)), new Set([".01ms !important"]));
  assert.deepEqual(new Set(declared("animation-iteration-count", reduced)), new Set(["1 !important"]));
  assert.deepEqual(new Set(declared("scroll-behavior", reduced)), new Set(["auto !important"]));

  const forced = "@media (forced-colors: active)";
  assert.ok(minnesota.some((rule) => rule.context === forced), "no Minnesota rule exists inside the forced-colors query");
  assert.deepEqual(new Set(declared("border-color", forced)), new Set(["CanvasText"]));
  assert.deepEqual(new Set(declared("forced-color-adjust", forced)), new Set(["auto"]));
});

test("text scales with the user's font size instead of being pinned in pixels", () => {
  // `clamp()` on a rem basis: the whole control room, its headings and its body
  // copy grow with the root font size rather than being frozen at one value.
  const root = minnesota.find((rule) => rule.selector === ".minnesota-control-room" && rule.context === "");
  const rootFont = root.declarations.find((entry) => entry.startsWith("font:"));
  assert.match(rootFont ?? "", /^font: 400 clamp\(1rem, \.96rem \+ \.16vw, 1\.125rem\) \/ 1\.6 /);
  const h1Sizes = minnesota
    .filter((rule) => rule.selector.endsWith("h1") && rule.context === "")
    .flatMap((rule) => rule.declarations)
    .filter((entry) => entry.startsWith("font-size:"));
  assert.deepEqual(h1Sizes, ["font-size: clamp(1.75rem, 6vw, 3.25rem)"]);
  // Long, unbreakable identifiers (artifact ids, digests, run revisions) wrap
  // instead of forcing a horizontal scroll at 200% zoom.
  assert.ok(declared("overflow-wrap").every((value) => value === "anywhere"));
  assert.ok(declared("overflow-wrap").length >= 2, "code and body copy must both wrap");
  assert.deepEqual(declared("font-size").filter((value) => /\d+px/.test(value)), []);
});

// --- contrast -------------------------------------------------------------

/** WCAG 2.x relative luminance of an `#rrggbb` colour. */
function luminance(hex) {
  const channels = [1, 3, 5].map((offset) => Number.parseInt(hex.slice(offset, offset + 2), 16) / 255);
  const [r, g, b] = channels.map((value) => (value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function ratio(foreground, background) {
  const [a, b] = [luminance(foreground), luminance(background)].sort((x, y) => y - x);
  return (a + 0.05) / (b + 0.05);
}

/** The `--mn-*` custom properties, read out of the sheet rather than restated. */
const tokens = Object.fromEntries(
  minnesota
    .filter((rule) => rule.selector === ".minnesota-control-room" && rule.context === "")
    .flatMap((rule) => rule.declarations)
    .filter((declaration) => declaration.startsWith("--mn-"))
    .map((declaration) => {
      const [name, value] = declaration.split(":");
      return [name.trim(), value.trim()];
    }),
);

test("the contrast the palette actually composites clears the repo's own targets", () => {
  // Targets: 4.5:1 text, 3:1 non-text (docs/design/ui-style-guide.md).
  // Each pair is pinned to the ratio it has today, so a token edit that keeps
  // the pair above threshold but changes the palette is still a visible change.
  const pairs = [
    ["--mn-text on --mn-surface", tokens["--mn-text"], tokens["--mn-surface"], 16.19, 4.5],
    ["--mn-text on the gradient start", tokens["--mn-text"], "#102d49", 13.07, 4.5],
    ["--mn-muted on the raised panel", tokens["--mn-muted"], tokens["--mn-surface-raised"], 9.79, 4.5],
    ["the eyebrow on the raised panel", tokens["--mn-accent"], tokens["--mn-surface-raised"], 10.48, 4.5],
    ["the button label on its accent fill", "#061725", tokens["--mn-accent"], 12.99, 4.5],
    ["the hovered button label", tokens["--mn-text"], "#155877", 7.25, 4.5],
    ["the disabled button label", "#d8e2ed", "#43566a", 5.77, 4.5],
    ["code on its own background", "#fff4cf", "#172639", 13.91, 4.5],
    ["the status line on the raised panel", "#fff0c2", tokens["--mn-surface-raised"], 12.9, 4.5],
    ["the failure heading on the raised panel", tokens["--mn-danger"], tokens["--mn-surface-raised"], 9.08, 4.5],
    ["--mn-border against the raised panel", tokens["--mn-border"], tokens["--mn-surface-raised"], 3.78, 3],
    ["the focus ring against the panel behind it", tokens["--mn-focus"], tokens["--mn-surface-raised"], 11.6, 3],
    ["the disabled border against its fill", "#aab9c7", "#43566a", 3.77, 3],
  ];
  for (const [label, foreground, background, expected, target] of pairs) {
    assert.ok(foreground && background, `${label}: a token in this pair is not declared`);
    const measured = ratio(foreground, background);
    assert.ok(measured >= target, `${label} is ${measured.toFixed(2)}:1, below the ${target}:1 target`);
    assert.equal(
      Number(measured.toFixed(2)),
      expected,
      `${label} is ${measured.toFixed(2)}:1, not the pinned ${expected}:1`,
    );
  }
});

// --- the wire -------------------------------------------------------------

test("the rules reach the stylesheet the browser downloads", async () => {
  // `npm run build` runs before `node --test` in gate/web, so dist/ is current.
  const shipped = parseRules(await readCss("dist/assets/app.css"));
  const shippedMinnesota = shipped.filter((rule) => rule.selector.includes(".minnesota-control-room"));
  assert.ok(shippedMinnesota.length >= 20, `only ${shippedMinnesota.length} Minnesota rules reached the built sheet`);
  for (const context of ["@media (prefers-reduced-motion: reduce)", "@media (forced-colors: active)"]) {
    assert.ok(
      shippedMinnesota.some((rule) => rule.context === context),
      `the built sheet carries no Minnesota rule inside ${context}`,
    );
  }
  assert.ok(
    shippedMinnesota.some((rule) => rule.selector.endsWith(":focus-visible") && rule.context === ""),
    "the built sheet carries no Minnesota :focus-visible rule",
  );
  const html = await readFile(fileURLToPath(new URL("dist/index.html", webRoot)), "utf8");
  assert.match(html, /<link[^>]+href="[^"]*assets\/app\.css"/, "the shell does not link the built stylesheet");
});
