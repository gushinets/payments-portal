import { expect, test } from "@playwright/test";

for (const locale of ["ru", "en"] as const) {
  test(`${locale} headings and body render with the Portal font`, async ({ page }, testInfo) => {
    await page.goto(`/${locale}`);
    await expect(page.locator("main h1")).toBeVisible();
    await page.evaluate(async () => {
      await document.fonts.ready;
    });

    const session = await page.context().newCDPSession(page);
    await session.send("DOM.enable");
    await session.send("CSS.enable");

    try {
      const selectors = ["main h1", "main p", ".logo"];
      if (locale === "ru") {
        // Exercise the whole basic Cyrillic block, including Ё/ё, using the
        // application's inherited body font rather than assigning a test font.
        await page.evaluate(async () => {
          const probe = document.createElement("p");
          probe.id = "portal-font-coverage-probe";
          probe.textContent = Array.from({ length: 96 }, (_, index) =>
            String.fromCodePoint(0x0400 + index)
          ).join("");
          document.body.append(probe);
          await document.fonts.ready;
        });
        selectors.push("#portal-font-coverage-probe");
      }

      const { root } = await session.send("DOM.getDocument");
      for (const selector of selectors) {
        const { nodeId } = await session.send("DOM.querySelector", {
          nodeId: root.nodeId,
          selector
        });
        expect(nodeId, selector).toBeGreaterThan(0);
        const { fonts } = await session.send("CSS.getPlatformFontsForNode", { nodeId });
        await testInfo.attach(`rendered-font-${selector}`, {
          body: JSON.stringify({ locale, selector, fonts }, null, 2),
          contentType: "application/json"
        });

        // Computed font-family alone would miss per-glyph system fallbacks.
        expect(fonts.length, selector).toBeGreaterThan(0);
        for (const font of fonts) {
          // Chromium can expose the variable font's internal base-face name.
          expect(font.familyName, selector).toMatch(/^Manrope(?: ExtraLight)?$/);
          expect(font.isCustomFont, selector).toBe(true);
          expect(font.glyphCount, selector).toBeGreaterThan(0);
        }
      }
    } finally {
      await page.locator("#portal-font-coverage-probe").evaluateAll((probes) => {
        for (const probe of probes) {
          probe.remove();
        }
      });
      await session.detach();
    }
  });
}
