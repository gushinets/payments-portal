import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import ru from "../src/messages/ru.json";
import de from "../src/messages/de.json";
import fr from "../src/messages/fr.json";
import pt from "../src/messages/pt.json";

const key = "anytoolai_session_token_v1";
const email = "verified-portal@example.com";
const widths = [390, 520, 521, 540, 560, 640, 768, 860, 861];
for (const [locale, messages] of [["ru", ru], ["de", de], ["fr", fr], ["pt", pt]] as const) {
  test(`${locale} signed-in and signed-out header bounds at every breakpoint`, async ({ page }, testInfo) => {
    await page.route("**/api/auth/session", (route) => route.fulfill({ json: { authenticated: true, user: { tenant_id: "anytoolai", region: "ru", user_id: "11111111-1111-4111-8111-111111111111", email, email_verified: true } } }));
    await page.addInitScript((storageKey) => localStorage.setItem(storageKey, "header-token"), key);
    await page.goto(`/${locale}/account`);
    await expect(page.getByRole("banner").getByText(email, { exact: true })).toBeVisible();
    await page.getByRole("button", { name: messages.CookieBanner.acceptAction, exact: true }).click();
    await page.evaluate(async () => { await document.fonts.ready; });
    for (const authenticated of [true, false]) {
      if (!authenticated) {
        await page.evaluate((storageKey) => { localStorage.removeItem(storageKey); window.dispatchEvent(new Event("anytoolai_session_changed")); }, key);
        await expect(page.getByRole("banner").getByRole("button", { name: messages.Auth.header.signIn, exact: true })).toBeVisible();
      }
      for (const width of widths) {
        await page.setViewportSize({ width, height: 900 });
        const bounds = await page.getByRole("banner").evaluate((header) => {
          const rect = (selector: string) => {
            const element = header.querySelector(selector)!; const box = element.getBoundingClientRect();
            return { left: box.left, right: box.right, top: box.top, bottom: box.bottom };
          };
          return { logo: rect(".logo"), actions: rect(".nav-actions"), links: rect(".nav-links"), controls: [...header.querySelectorAll(".nav-actions > *, .nav-links > *")].map((element) => { const box = element.getBoundingClientRect(); return { left: box.left, right: box.right, top: box.top, bottom: box.bottom }; }), overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth };
        });
        const overlaps = (a: typeof bounds.logo, b: typeof bounds.logo) => a.left < b.right - 1 && b.left < a.right - 1 && a.top < b.bottom - 1 && b.top < a.bottom - 1;
        expect(overlaps(bounds.logo, bounds.actions), `${locale}/${authenticated}/${width}: logo/actions`).toBe(false);
        expect(overlaps(bounds.logo, bounds.links), `${locale}/${authenticated}/${width}: logo/links`).toBe(false);
        expect(overlaps(bounds.actions, bounds.links), `${locale}/${authenticated}/${width}: actions/links`).toBe(false);
        for (const box of [bounds.logo, ...bounds.controls]) { expect(box.left).toBeGreaterThanOrEqual(0); expect(box.right).toBeLessThanOrEqual(width); }
        expect(bounds.overflow).toBeLessThanOrEqual(0);
        if (width > 520 && width <= 860) expect(bounds.links.top).toBeGreaterThanOrEqual(Math.max(bounds.logo.bottom, bounds.actions.bottom));
        if ([520, 521, 540, 861].includes(width)) await page.getByRole("banner").screenshot({ path: testInfo.outputPath(`${locale}-${authenticated ? "authenticated" : "signed-out"}-${width}.png`) });
      }
      if (authenticated) {
        await page.setViewportSize({ width: 521, height: 900 });
        await page.keyboard.press("Tab");
        await page.getByRole("banner").locator(".logo").focus();
        await expect(page.getByRole("banner").locator(".logo")).toBeFocused();
        expect(await page.getByRole("banner").locator(".logo").evaluate((element) => getComputedStyle(element).outlineStyle)).not.toBe("none");
        await page.keyboard.press("Tab");
        expect(await page.getByRole("banner").evaluate((header) => header.contains(document.activeElement))).toBe(true);
        const accessibility = await new AxeBuilder({ page }).include("header").analyze();
        expect(accessibility.violations.filter(({ impact }) => impact === "serious" || impact === "critical")).toEqual([]);
      }
    }
  });
}
