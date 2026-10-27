import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Locator, type Page, type TestInfo } from "@playwright/test";

import ruMessages from "../src/messages/ru.json";

const removedContracts = [
  "/api/auth/checkout-intent",
  "/api/account/subscriptions",
  "/api/auth/payment-status"
];
// Match complete subscription/access nouns, never the adjective in
// "Нет доступных продуктов" (a valid empty technical catalog).
const inventedSubscriptionState = /нет\s+(?:активн[а-яё]+\s+)?(?:подписки|подписок|подписка|подписку|доступа?)(?![а-яё])|(?:подписк[аи]|доступа?)\s+(?:нет|отсутству(?:ет|ют))(?![а-яё])|no\s+(?:active\s+)?(?:subscriptions?|access)\b/iu;

test("subscription-state guard permits an empty catalog but rejects invented access facts", () => {
  expect(ruMessages.CatalogPreview.empty).not.toMatch(inventedSubscriptionState);
  for (const unsupported of ["Нет подписки", "Нет активных подписок", "Нет доступа", "Подписка отсутствует", "Доступа нет", "No subscription", "No access"]) {
    expect(unsupported).toMatch(inventedSubscriptionState);
  }
});

test.beforeEach(async ({ page }) => {
  // These layout journeys cover a genuinely empty technical catalog. Unknown
  // product IDs are 404; source outages are covered separately in catalog-preview.
  // Positive source-ID and exact-money coverage lives in catalog-preview.spec.
  await page.route("**/api/catalog/products", (route) => route.fulfill({ json: { products: [] } }));
  await page.route("**/api/catalog/products/*", (route) => route.fulfill({
    status: 404, json: { detail: { code: "catalog_product_not_found" } }
  }));
  await page.route("**/api/purchase-intents", (route) => route.fulfill({ json: { purchases: [], next_cursor: null } }));
  await page.route("**/api/purchase-intents/current?*", (route) => route.fulfill({ json: { purchase: null } }));
});
const portalRoutes = [
  "/ru",
  "/ru/products",
  "/ru/pricing",
  "/ru/products/document-summary",
  "/ru/products/prompt-optimizer",
  "/ru/account"
];

function observePortalTraffic(page: Page) {
  const removedContractRequests: string[] = [];
  const scriptRequests: string[] = [];
  const apiRequests: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname.startsWith("/api/")) {
      apiRequests.push(`${request.method()} ${url.pathname}`);
    }
    if (removedContracts.includes(url.pathname.replace(/\/+$/, ""))) {
      removedContractRequests.push(`${request.method()} ${url.pathname}`);
    }
    if (request.resourceType() === "script") {
      scriptRequests.push(`${url.origin}${url.pathname}`);
    }
  });

  return { removedContractRequests, scriptRequests, apiRequests };
}

async function expectPortalBoundary(
  page: Page,
  traffic: ReturnType<typeof observePortalTraffic>,
  testInfo: TestInfo
) {
  const portalOrigin = new URL(page.url()).origin;
  const scriptSources = await page.locator("script[src]").evaluateAll((scripts) =>
    scripts.map((script) => script.getAttribute("src") ?? "")
  );
  const externalScriptRequests = traffic.scriptRequests.filter((url) =>
    new URL(url).origin !== portalOrigin
  );
  const externalScriptSources = scriptSources.filter((source) =>
    new URL(source, page.url()).origin !== portalOrigin
  );
  const providerScriptRequests = traffic.scriptRequests.filter((url) =>
    /cloudpayments|provider-adapters/i.test(url)
  );
  const providerScriptSources = scriptSources.filter((source) =>
    /cloudpayments|provider-adapters/i.test(source)
  );
  const hasCloudPaymentsSdk = await page.evaluate(() => "cp" in window);

  await testInfo.attach("portal-boundary-evidence", {
    body: JSON.stringify({
      route: new URL(page.url()).pathname,
      ...traffic,
      externalScriptRequests,
      externalScriptSources,
      providerScriptRequests,
      providerScriptSources,
      hasCloudPaymentsSdk
    }, null, 2),
    contentType: "application/json"
  });

  expect(traffic.removedContractRequests).toEqual([]);
  expect(providerScriptRequests).toEqual([]);
  expect(providerScriptSources).toEqual([]);
  expect(hasCloudPaymentsSdk).toBe(false);

  // Public browsing and local owned inventory do not open billing or create purchases.
  expect(traffic.apiRequests.filter((request) => request !== "GET /api/auth/session" &&
    request !== "GET /api/purchase-intents" &&
    !request.startsWith("GET /api/catalog/products")))
    .toEqual([]);
  const main = page.getByRole("main");
  const footer = page.getByRole("contentinfo");
  const navigation = page.getByRole("navigation", { name: ruMessages.Navigation.mainAriaLabel });
  await expect(main).not.toContainText(/CloudPayments/i);
  await expect(footer).not.toContainText(/CloudPayments/i);
  await expect(navigation).not.toContainText(/CloudPayments/i);
  await expect(main).not.toContainText(/(?:490|990)\s*₽|200\s*k\s*\+|320\s*\/\s*500|3\s*\/\s*10/i);
  await expect(footer).not.toContainText(/(?:490|990)\s*₽|200\s*k\s*\+|320\s*\/\s*500|3\s*\/\s*10/i);
  await expect(main).not.toContainText(inventedSubscriptionState);
  await expect(main).not.toContainText(
    /\d[\d\s.,]*\s*(?:₽|руб|RUB|€|\$)|[€$₽]\s*\d/i
  );
  await expect(main).not.toContainText(/\b(?:free|pro|default)\b|бесплатн[а-яё]*|по умолчанию/i);
  await expect(main).not.toContainText(
    /(?:^|\D)0\s*(?:\/\s*\d+|(?:из|of)\s+\d+|(?:запрос|использован|usage|quota))/i
  );
}

async function expectKeyboardFocus(page: Page, target: Locator) {
  // Reach the action through the real tab order rather than assigning focus.
  for (let attempt = 0; attempt < 24; attempt += 1) {
    await page.keyboard.press("Tab");
    if (await target.evaluate((element) => element === document.activeElement)) {
      break;
    }
  }
  await expect(target).toBeFocused();
  await expect(target).toBeInViewport();
  await expect.poll(() => target.evaluate((element) => {
    const style = window.getComputedStyle(element);
    return style.outlineStyle !== "none" &&
      Number.parseFloat(style.outlineWidth) > 0 &&
      style.outlineColor !== "transparent" &&
      style.outlineColor !== "rgba(0, 0, 0, 0)";
  })).toBe(true);
}

async function capturePortalScreenshot(page: Page, testInfo: TestInfo, name: string) {
  await page.evaluate(async () => {
    await document.fonts.ready;
    window.scrollTo(0, 0);
  });
  const screenshotPath = testInfo.outputPath(`${name}.png`);
  await page.screenshot({
    path: screenshotPath,
    animations: "disabled",
    caret: "hide",
    scale: "css",
    fullPage: true
  });
  await testInfo.attach(name, { path: screenshotPath, contentType: "image/png" });
  await testInfo.attach(`${name}-review-context`, {
    body: JSON.stringify({
      route: new URL(page.url()).pathname,
      viewport: page.viewportSize(),
      reference: "ANY-539 portal-ru-anytools.html (input-only local reference, not committed)",
      review: "Compare composition and navy background, flat dark surfaces, thin borders, amber accent, compact radii/spacing, typography and dashboard/cards. Purple/indigo glass and bento must not dominate. Human review only; no pixel baseline."
    }, null, 2),
    contentType: "application/json"
  });
}

async function expectNoHorizontalOverflow(page: Page) {
  await expect.poll(() => page.evaluate(() =>
    Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) -
    document.documentElement.clientWidth
  )).toBeLessThanOrEqual(0);
}

async function expectMobileLayout(page: Page, testInfo: TestInfo, name: string) {
  await expectNoHorizontalOverflow(page);

  await testInfo.attach(`mobile-${name}-runtime-evidence`, {
    body: JSON.stringify(await page.evaluate(() => ({
      route: window.location.pathname,
      viewportWidth: document.documentElement.clientWidth,
      documentWidth: document.documentElement.scrollWidth,
      bodyWidth: document.body.scrollWidth
    })), null, 2),
    contentType: "application/json"
  });
  await capturePortalScreenshot(page, testInfo, `mobile-${name}`);
}

for (const route of portalRoutes) {
  test(`${route} stays independent of removed commerce contracts and provider scripts`, async ({
    page
  }, testInfo) => {
    const traffic = observePortalTraffic(page);
    const response = await page.goto(route, { waitUntil: "networkidle" });

    expect(response?.status()).toBe(200);
    await expect(page.getByRole("main").getByRole("heading", { level: 1 })).toBeVisible();
    if (route === "/ru/account") {
      await expect(
        page.getByRole("main").getByRole("heading", { name: "Вход или регистрация" })
      ).toBeVisible();
    }
    if (route === "/ru" || route === "/ru/products") {
      await expect(page.getByRole("main").getByRole("status")).toHaveText(ruMessages.CatalogPreview.empty);
      await expect(page.getByRole("main").getByRole("article")).toHaveCount(0);
    }
    expect(traffic.apiRequests.filter((request) => !request.startsWith("GET /api/catalog/products"))).toEqual([]);

    await expectPortalBoundary(page, traffic, testInfo);
  });
}

test("home preserves account entry and discovery with an empty technical catalog", async ({
  page
}, testInfo) => {
  const traffic = observePortalTraffic(page);
  await page.goto("/ru", { waitUntil: "networkidle" });
  await page.getByRole("button", { name: ruMessages.CookieBanner.acceptAction, exact: true }).click();
  const main = page.getByRole("main");
  const heading = main.getByRole("heading", {
    level: 1,
    name: ruMessages.Home.hero.heading.replace(/<\/?em>/g, ""),
    exact: true
  });
  const hero = main.locator("section").filter({ has: page.getByRole("heading", { level: 1 }) });
  await expect(heading).toBeVisible();
  await expect(hero.getByText(ruMessages.Home.hero.description, { exact: true })).toBeVisible();
  await expect(hero.getByRole("link")).toHaveText([
    ruMessages.Home.hero.primaryAction,
    ruMessages.Home.hero.secondaryAction
  ]);
  const accountAction = hero.getByRole("link", { name: ruMessages.Home.hero.primaryAction });
  const discoveryAction = hero.getByRole("link", { name: ruMessages.Home.hero.secondaryAction });
  await expect(accountAction).toHaveAttribute("href", "/ru/account");
  await expect(discoveryAction).toHaveAttribute("href", "#products");

  const discovery = main.locator("#products");
  await expect(discovery.getByRole("heading", {
    level: 2,
    name: ruMessages.Home.products.title,
    exact: true
  })).toBeVisible();
  await expect(discovery.getByRole("link", { name: ruMessages.Home.products.action, exact: true }))
    .toHaveAttribute("href", "/ru/products");
  await expect(discovery.getByRole("status")).toHaveText(ruMessages.CatalogPreview.empty);
  await expect(discovery.getByRole("article")).toHaveCount(0);
  await expect(main).not.toContainText(/Proposal Checker|Scope Guard|следующий инструмент|лист ожидания/i);

  const navigation = page.getByRole("navigation", { name: ruMessages.Navigation.mainAriaLabel });
  await expectKeyboardFocus(page, navigation.getByRole("link", { name: ruMessages.Navigation.products, exact: true }));
  await expectKeyboardFocus(page, accountAction);
  await expectKeyboardFocus(page, discoveryAction);
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/ru#products$/);
  await expect(discovery.getByRole("heading", { level: 2 })).toBeInViewport();
  await expectNoHorizontalOverflow(page);
  expect(traffic.apiRequests).toContain("GET /api/catalog/products");
  await expectPortalBoundary(page, traffic, testInfo);
});

for (const authenticated of [false, true]) {
  test(`home account entry and product purchase controls preserve account navigation (authenticated: ${authenticated})`, async ({
    page
  }) => {
    const email = "cta-portal@example.com";
    if (authenticated) {
      await page.addInitScript(() => {
        window.localStorage.setItem("anytoolai_session_token_v1", "cta-session");
      });
      await page.route("**/api/auth/session", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            authenticated: true,
            user: {
              tenant_id: "anytoolai",
              region: "ru",
              user_id: "11111111-1111-4111-8111-111111111111",
              email,
              email_verified: true
            }
          })
        });
      });
    }

    for (const pathname of ["/ru", "/ru/products/proposal_ai"]) {
      await page.goto(pathname, { waitUntil: "networkidle" });
      if (pathname === "/ru") {
        await page.getByRole("button", { name: ruMessages.CookieBanner.acceptAction, exact: true }).click();
      }
      const main = page.getByRole("main");
      let accountAction: Locator;
      if (pathname === "/ru") {
        accountAction = main.getByRole("link", { name: ruMessages.Catalog.signInAction, exact: true });
      } else {
        const purchase = main.getByRole("region", { name: ruMessages.Purchase.title });
        if (authenticated) {
          await expect(purchase.getByRole("button", { name: ruMessages.Purchase.buy, exact: true })).toBeEnabled();
          await expect(purchase.getByRole("button", { name: ruMessages.Billing.open, exact: true })).toHaveCount(0);
          accountAction = page.getByRole("navigation", { name: ruMessages.Navigation.mainAriaLabel })
            .getByRole("link", { name: `${email} ${ruMessages.Auth.header.accountArea}`, exact: true });
        } else {
          accountAction = purchase.getByRole("link", { name: ruMessages.Purchase.signIn, exact: true });
        }
      }
      await expect(accountAction).toHaveAttribute("href", "/ru/account");
      await accountAction.click();
      await expect(page).toHaveURL(/\/ru\/account$/);
      if (authenticated) {
        await expect(main.getByText(email, { exact: true })).toBeVisible();
        await expect(main.getByRole("heading", { name: ruMessages.Account.title, exact: true })).toBeVisible();
      } else {
        await expect(main.getByRole("heading", { name: "Вход или регистрация", exact: true })).toBeVisible();
      }
    }
  });
}

for (const route of [
  "/ru/auth-checkout",
  "/ru/payment-result"
]) {
  test(`${route} is not found without a compatibility redirect`, async ({ page, request }) => {
    const directResponse = await request.get(route, { maxRedirects: 0 });
    expect(directResponse.status()).toBe(404);
    expect(directResponse.headers().location).toBeUndefined();

    const response = await page.goto(route, { waitUntil: "networkidle" });
    expect(response?.status()).toBe(404);
    expect(response?.request().redirectedFrom()).toBeNull();
    expect(new URL(page.url()).pathname).toBe(route);
    await expect(page.getByRole("heading", { name: "404", exact: true })).toBeVisible();
    await expect(page).toHaveURL(new RegExp(`${route}$`));
  });
}

for (const emailVerified of [true, false]) {
  test(`account preserves identity and email verification with an empty catalog (email verified: ${emailVerified})`, async ({
    page
  }, testInfo) => {
    const traffic = observePortalTraffic(page);
    if (testInfo.project.use.isMobile) {
      await page.setViewportSize({ width: 390, height: 844 });
    }
    const email = emailVerified ? "verified-portal@example.com" : "pending-portal@example.com";
    await page.addInitScript(() => {
      window.localStorage.setItem("anytoolai_session_token_v1", "portal-session");
    });
    await page.route("**/api/auth/session", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          authenticated: true,
          user: {
            tenant_id: "anytoolai",
            region: "ru",
            user_id: "11111111-1111-4111-8111-111111111111",
            email,
            email_verified: emailVerified
          }
        })
      });
    });

    await page.goto("/ru/account", { waitUntil: "networkidle" });
    await page.getByRole("button", { name: ruMessages.CookieBanner.acceptAction, exact: true }).click();
    const main = page.getByRole("main");
    await expect(main.getByRole("heading", { level: 1, name: ruMessages.Account.title })).toBeVisible();
    await expect(main.locator("h1")).toHaveCount(1);
    const headingTags = await main.locator("h1, h2, h3, h4, h5, h6").evaluateAll((headings) => headings.map((heading) => heading.tagName));
    expect(headingTags[0]).toBe("H1");
    expect(headingTags.slice(1)).toEqual(emailVerified ? ["H2", "H2", "H2"] : ["H2", "H2", "H2", "H2"]);
    const identity = main.getByRole("complementary", { name: ruMessages.Account.authenticated.summaryTitle });
    await expect(identity.getByRole("heading", { level: 2, name: ruMessages.Account.authenticated.summaryTitle })).toBeVisible();
    await expect(identity.getByRole("term")).toHaveText([ruMessages.Account.authenticated.emailLabel]);
    await expect(identity.getByRole("definition")).toHaveText([email]);
    await expect(identity.getByRole("article")).toHaveCount(0);
    await expect(main.getByText(email, { exact: true })).toBeVisible();
    await expect(main.getByText(
      emailVerified ? "Email подтверждён" : "Email не подтверждён",
      { exact: true }
    )).toBeVisible();
    const verificationHeading = identity.getByRole("heading", { level: 2, name: "Подтвердите email", exact: true });
    if (emailVerified) {
      await expect(verificationHeading).toHaveCount(0);
    } else {
      await expect(verificationHeading).toBeVisible();
      await expect(main.getByRole("button", { name: "Отправить письмо ещё раз" })).toBeEnabled();
    }

    const productRegion = main.getByRole("region", { name: ruMessages.Account.products.title });
    await expect(productRegion.getByRole("heading", { level: 2, name: ruMessages.Account.products.title, exact: true })).toBeVisible();
    const billingRegion = main.getByRole("region", { name: ruMessages.Billing.title, exact: true });
    await expect(billingRegion.getByRole("heading", { level: 2, name: ruMessages.Billing.title, exact: true })).toBeVisible();
    const openBilling = billingRegion.getByRole("button", { name: ruMessages.Billing.open, exact: true });
    if (emailVerified) {
      await expect(openBilling).toBeEnabled();
    } else {
      await expect(openBilling).toBeDisabled();
    }
    const headingBox = await main.getByRole("heading", { level: 1 }).boundingBox();
    const identityBox = await identity.boundingBox();
    const productBox = await productRegion.boundingBox();
    expect(headingBox).not.toBeNull();
    expect(identityBox).not.toBeNull();
    expect(productBox).not.toBeNull();
    if (testInfo.project.use.isMobile) {
      expect(headingBox!.y + headingBox!.height).toBeLessThanOrEqual(identityBox!.y);
      expect(identityBox!.y + identityBox!.height).toBeLessThanOrEqual(productBox!.y);
    } else {
      expect(identityBox!.x + identityBox!.width).toBeLessThanOrEqual(headingBox!.x);
      expect(identityBox!.x + identityBox!.width).toBeLessThanOrEqual(productBox!.x);
      expect(headingBox!.y + headingBox!.height).toBeLessThanOrEqual(productBox!.y);
    }
    await expect(productRegion.getByText(ruMessages.Account.products.empty)).toBeVisible();
    await expect(productRegion.getByRole("article")).toHaveCount(0);
    await expect(productRegion.getByRole("link", { name: ruMessages.Account.products.allProducts })).toHaveAttribute("href", "/ru/products");
    await expect(main).not.toContainText(inventedSubscriptionState);
    await expect(main).not.toContainText(
      /\d[\d\s.,]*\s*(?:₽|руб|RUB|€|\$)|[€$₽]\s*\d/i
    );

    const accessibility = await new AxeBuilder({ page }).analyze();
    const seriousOrCritical = accessibility.violations.filter((violation) =>
      violation.impact === "serious" || violation.impact === "critical"
    );
    await testInfo.attach("account-accessibility-evidence", {
      body: JSON.stringify(seriousOrCritical, null, 2),
      contentType: "application/json"
    });
    expect(seriousOrCritical).toEqual([]);
    await expectPortalBoundary(page, traffic, testInfo);
    await expectNoHorizontalOverflow(page);
    const viewport = testInfo.project.use.isMobile ? "mobile" : "desktop";
    const verificationState = emailVerified ? "verified" : "pending-verification";
    await capturePortalScreenshot(page, testInfo, `${viewport}-account-${verificationState}`);
    if (!emailVerified) {
      await expectKeyboardFocus(page, identity.getByRole("button", { name: ruMessages.EmailVerification.pending.resend }));
    }
    await expectKeyboardFocus(page, identity.getByRole("button", { name: ruMessages.Account.authenticated.signOutAction }));
    expect(traffic.apiRequests.filter((request) => request.includes("/api/billing/widget-bootstrap"))).toEqual([]);
    expect(traffic.scriptRequests.filter((url) => new URL(url).pathname === "/lbxwidget.js")).toEqual([]);
    await expect(billingRegion.locator("iframe")).toHaveCount(0);
  });
}

test("RU Portal navigation, product discovery and account forms remain usable at 390x844", async ({
  page
}, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const traffic = observePortalTraffic(page);
  await page.goto("/ru", { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Принять", exact: true }).click();

  const navigation = page.getByRole("navigation", { name: "Основная навигация" });
  await expect(navigation.getByRole("button", { name: "Войти", exact: true })).toBeEnabled();
  const catalogLink = navigation.getByRole("link", { name: "AI-утилиты", exact: true });
  await expect(catalogLink).toBeInViewport();
  await expectMobileLayout(page, testInfo, "home");
  await catalogLink.click();
  await expect(page).toHaveURL(/\/ru\/products$/);

  const main = page.getByRole("main");
  await expect(main.getByRole("heading", { level: 1, name: "AI-утилиты" })).toBeVisible();
  await expect(main.getByRole("status")).toHaveText(ruMessages.CatalogPreview.empty);
  await expectMobileLayout(page, testInfo, "catalog-empty");
  await page.goto("/ru/products/proposal_ai", { waitUntil: "networkidle" });
  await expect(main.getByRole("heading", { level: 1, name: ruMessages.CatalogPreview.productTitle })).toBeVisible();
  await expect(main.getByRole("status")).toHaveText(ruMessages.CatalogPreview.notFound);
  await expectMobileLayout(page, testInfo, "product-not-found");

  await expectKeyboardFocus(page, main.getByRole("link", { name: ruMessages.Purchase.signIn, exact: true }));
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/ru\/account$/);
  await expect(main.getByRole("heading", { name: "Вход или регистрация" })).toBeVisible();
  await expectKeyboardFocus(page, main.getByLabel("Email"));
  await main.getByLabel("Email").fill("mobile-portal@example.com");
  await page.keyboard.press("Tab");
  await expect(main.getByLabel("Пароль", { exact: true })).toBeFocused();
  await main.getByLabel("Пароль", { exact: true }).fill("Synthetic-password-123!");
  await expect(main.getByRole("button", { name: "Войти", exact: true })).toBeEnabled();
  await expect(main.getByRole("link", { name: "Забыли пароль?" }))
    .toHaveAttribute("href", "/ru/forgot-password");
  await expectMobileLayout(page, testInfo, "account-login");

  await main.getByRole("button", { name: "Регистрация", exact: true }).click();
  const confirmation = main.getByLabel("Повторите пароль");
  await confirmation.fill("Synthetic-password-123!");
  await expect(confirmation).toBeInViewport();
  await expect(confirmation).toHaveValue("Synthetic-password-123!");
  await expect(main.getByRole("checkbox")).toHaveCount(2);
  await main.getByRole("checkbox").first().check();
  await main.getByRole("checkbox").last().check();
  await expect(main.getByRole("button", { name: "Создать аккаунт", exact: true })).toBeEnabled();
  await expectMobileLayout(page, testInfo, "account-registration");
  await expectPortalBoundary(page, traffic, testInfo);
});
