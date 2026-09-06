import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

/**
 * The browser proof for 2WKG-401.
 *
 * The rest of this ticket's evidence is CSS-level: rules parsed out of
 * `src/styles.css` and out of the built `dist/assets/app.css`. That proves the
 * rules ship; it cannot prove a browser applies them. This spec loads the real
 * built page through the real `server.mjs` and asserts the two claims that only
 * a browser can settle -- that keyboard focus paints a ring, and that axe finds
 * no violation on the route.
 */
test("the Minnesota control room has no axe-detectable accessibility violations", async ({ page }) => {
  await page.goto("/minnesota");
  await expect(page.locator("main.minnesota-control-room")).toBeVisible();

  const results = await new AxeBuilder({ page })
    .include("main.minnesota-control-room")
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();

  expect(
    results.violations.map((violation) => `${violation.id}: ${violation.help}`),
    JSON.stringify(results.violations, null, 2),
  ).toEqual([]);
});

test("keyboard focus paints the high-visibility ring, and the disabled control is not a tab stop", async ({ page }) => {
  await page.goto("/minnesota");
  const reset = page.getByRole("button", { name: "Reset to baseline" });
  await expect(reset).toBeVisible();

  await reset.focus();
  const ring = await reset.evaluate((element) => {
    const style = getComputedStyle(element);
    return { width: style.outlineWidth, style: style.outlineStyle, color: style.outlineColor, offset: style.outlineOffset };
  });
  expect(ring.style).not.toBe("none");
  expect(Number.parseFloat(ring.width)).toBeGreaterThan(0);
  // `--mn-focus: #ffe47a`, resolved by the browser rather than read off the sheet.
  expect(ring.color).toBe("rgb(255, 228, 122)");
  // The offset is what keeps the ring off the button's own accent fill, where it
  // would only reach 1.11:1.
  expect(Number.parseFloat(ring.offset)).toBeGreaterThan(0);

  // The unavailable inspect control is disabled, so tabbing never lands on it.
  const disabled = page.getByRole("button", { name: "Inspect feature unavailable", includeHidden: true });
  await expect(disabled).toBeDisabled();
  const focusedNames: string[] = [];
  for (let index = 0; index < 12; index += 1) {
    await page.keyboard.press("Tab");
    focusedNames.push(await page.evaluate(() => document.activeElement?.textContent?.trim() ?? ""));
  }
  expect(focusedNames).not.toContain("Inspect feature unavailable");
});

test("the reduced-motion and forced-colors rules are live rules in the browser, not text in a file", async ({ page }) => {
  await page.goto("/minnesota");
  const conditions = await page.evaluate(() => {
    const found: string[] = [];
    for (const sheet of Array.from(document.styleSheets)) {
      let rules: CSSRuleList;
      try {
        rules = sheet.cssRules;
      } catch {
        continue;
      }
      for (const rule of Array.from(rules)) {
        if (!(rule instanceof CSSMediaRule)) continue;
        const applies = Array.from(rule.cssRules).some(
          (inner) => inner instanceof CSSStyleRule && inner.selectorText.includes(".minnesota-control-room"),
        );
        if (applies) found.push(rule.conditionText);
      }
    }
    return found;
  });
  expect(conditions).toContain("(prefers-reduced-motion: reduce)");
  expect(conditions).toContain("(forced-colors: active)");
});

test("under prefers-reduced-motion the control room's transitions are effectively off", async ({ browser }) => {
  const context = await browser.newContext({ reducedMotion: "reduce" });
  const page = await context.newPage();
  await page.goto("/minnesota");
  await expect(page.locator("main.minnesota-control-room")).toBeVisible();
  const durations = await page.evaluate(() => {
    const root = document.querySelector("main.minnesota-control-room");
    return Array.from(root?.querySelectorAll("*") ?? []).map((element) => ({
      transition: getComputedStyle(element).transitionDuration,
      animation: getComputedStyle(element).animationDuration,
    }));
  });
  expect(durations.length).toBeGreaterThan(0);
  // The sentinel the rule sets (`.01ms !important`). The browser default is
  // `0s`, so this distinguishes "the reduced-motion rule applied" from "there
  // was never a transition here" -- an assertion that a removed rule passes is
  // not an assertion.
  for (const { transition, animation } of durations) {
    expect(Number.parseFloat(transition)).toBe(0.00001);
    expect(Number.parseFloat(animation)).toBe(0.00001);
  }
  await context.close();
});
