/**
 * The prohibited decorative status word must not reach the shipped artifact as
 * a status token or a truth label.
 *
 * `src/status-vocabulary.test.mjs` guards the design documents and
 * `src/layers/legend.test.mjs` guards the legend, but nothing guarded the
 * built bundle: PR #290 rendered the word as a `data-truth-label` on every
 * operation and its own test asserted the violation, with the whole suite
 * green. Three frozen contracts refuse it by name --
 * `docs/design/3d-asset-contract.md` ("There is deliberately no decorative or
 * ... state"), `docs/design/texas-demo-narrative-ia.md` ("prohibited
 * browser-invented status ... Do not display or synthesize it") and
 * `docs/design/minnesota-gate-0-approval.md` ("not approved").
 *
 * The word is legitimate English prose on the explainer page ("an illustrative
 * epoch"), so the assertion is on the shapes a *status* takes: a complete
 * quoted token, and any `data-*` attribute value. Comments are stripped first,
 * because a comment explaining the prohibition is not a claim.
 */
import assert from "node:assert/strict";
import test from "node:test";

import { readBuiltScripts } from "./built-assets.mjs";
import { stripComments } from "../scripts/check-browser-boundary.mjs";

/** Spelled once here so the guarantee can be stated without seeding the term. */
const PROHIBITED_STATUS_WORD = ["illus", "trative"].join("");

const built = stripComments(await readBuiltScripts());

test("the built bundle carries no prohibited status token", () => {
  const quotedToken = new RegExp(`["'\`]${PROHIBITED_STATUS_WORD}["'\`]`, "i");
  const match = built.match(quotedToken);
  assert.equal(
    match,
    null,
    `the shipped bundle carries the prohibited status word as a token: ${built.slice(Math.max(0, (match?.index ?? 0) - 80), (match?.index ?? 0) + 80)}`,
  );
});

test("no rendered data attribute in the bundle is bound to the prohibited word", () => {
  const attributeBinding = new RegExp(`data-[a-z0-9-]+\\s*[:=]\\s*["'\`]?${PROHIBITED_STATUS_WORD}`, "i");
  assert.doesNotMatch(built, attributeBinding);
  // The capitalised chip the panel used to render.
  const chip = new RegExp(`>\\s*${PROHIBITED_STATUS_WORD}\\s*<`, "i");
  assert.doesNotMatch(built, chip);
});

test("the probe can tell the two states apart", () => {
  // A same-shaped token that is allowed proves the regexes match a token at all.
  const allowed = /["'`]hypothetical["'`]/;
  assert.match(built, allowed, "the six-token vocabulary should ship, so the probe is comparing like with like");
});
