import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type TestInfo } from "@playwright/test";

const removedContracts = [
  "/api/catalog/products",
  "/api/auth/checkout-intent",
  "/api/account/subscriptions",
  "/api/auth/payment-status"
];
const portalRoutes = [
  "/ru",
  "/ru/products",
  "/ru/products/document-summary",
  "/ru/products/prompt-optimizer",
  "/ru/account"
];
const products = [
  {
    slug: "document-summary",
    name: "Document Summary",
    title: "Мгновенное краткое содержание любого документа",
    description: "Расширение помогает быстро получать краткое содержание документов и веб-страниц без лишних ручных действий."
  },
  {
    slug: "prompt-optimizer",
    name: "Prompt Optimizer",
    title: "Улучшение промптов для ИИ в один клик",
    description: "Расширение улучшает промпты прямо в привычном интерфейсе и показывает, что именно стало лучше."
  }
] as const;
const readinessPanels = [
  {
    title: "Доступ",
    description: "Достоверный статус доступа к продуктам пока недоступен."
  },
  {
    title: "Биллинг и подписка",
    description: "Сведения о тарифе, подписке и биллинге пока не готовы."
  },
  {
    title: "Использование и квота",
    description: "Данные об использовании и квоте пока недоступны."
  }
];

function observePortalTraffic(page: Page) {
  const removedContractRequests: string[] = [];
  const scriptRequests: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (removedContracts.includes(url.pathname.replace(/\/+$/, ""))) {
      removedContractRequests.push(`${request.method()} ${url.pathname}`);
    }
    if (request.resourceType() === "script") {
      scriptRequests.push(`${url.origin}${url.pathname}`);
    }
  });

  return { removedContractRequests, scriptRequests };
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
}

async function expectMobileLayout(page: Page, testInfo: TestInfo, name: string) {
  await expect.poll(() => page.evaluate(() =>
    Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) -
    document.documentElement.clientWidth
  )).toBeLessThanOrEqual(0);

  await testInfo.attach(`mobile-${name}-runtime-evidence`, {
    body: JSON.stringify(await page.evaluate(() => ({
      route: window.location.pathname,
      viewportWidth: document.documentElement.clientWidth,
      documentWidth: document.documentElement.scrollWidth,
      bodyWidth: document.body.scrollWidth
    })), null, 2),
    contentType: "application/json"
  });
  await page.screenshot({
    path: testInfo.outputPath(`mobile-${name}.png`),
    fullPage: true
  });
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
      await expect(page.getByRole("main").getByRole("status")).toHaveCount(0);
      for (const product of products) {
        await expect(
          page.getByRole("main").getByRole("link", { name: new RegExp(product.title) })
        ).toHaveAttribute("href", `/ru/products/${product.slug}`);
      }
    }

    await expectPortalBoundary(page, traffic, testInfo);
  });
}

for (const product of products) {
  test(`catalog card opens the localized ${product.slug} detail page`, async ({ page }) => {
    await page.goto("/ru/products");
    const card = page.getByRole("main").getByRole("link", {
      name: new RegExp(product.title)
    });
    await expect(card).toContainText("Подробнее");
    await expect(card).toContainText(product.description);
    await expect(card).toHaveAttribute("href", `/ru/products/${product.slug}`);
    await card.click();

    await expect(page).toHaveURL(new RegExp(`/ru/products/${product.slug}$`));
    const main = page.getByRole("main");
    await expect(main.getByRole("heading", { level: 1, name: product.title })).toBeVisible();
    await expect(main.getByText(product.description, { exact: true })).toBeVisible();
    await expect(
      main.getByRole("link", { name: "Войти или зарегистрироваться" })
    ).toHaveAttribute("href", "/ru/account");
    const backLinks = main.getByRole("link", { name: "К списку продуктов" });
    await expect(backLinks).toHaveCount(2);
    for (const backLink of await backLinks.all()) {
      await expect(backLink).toHaveAttribute("href", "/ru/products");
    }
  });
}

for (const route of [
  "/ru/auth-checkout",
  "/ru/payment-result",
  "/ru/products/unknown-product"
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
  test(`account shows identity and unknown commercial data (email verified: ${emailVerified})`, async ({
    page
  }, testInfo) => {
    const traffic = observePortalTraffic(page);
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
    const main = page.getByRole("main");
    await expect(main.getByText(email, { exact: true })).toBeVisible();
    await expect(main.getByText(
      emailVerified ? "Email подтверждён" : "Email не подтверждён",
      { exact: true }
    )).toBeVisible();
    const verificationHeading = main.getByRole("heading", { name: "Подтвердите email", exact: true });
    if (emailVerified) {
      await expect(verificationHeading).toHaveCount(0);
    } else {
      await expect(verificationHeading).toBeVisible();
      await expect(main.getByRole("button", { name: "Отправить письмо ещё раз" })).toBeEnabled();
    }

    const productRegion = main.getByRole("region", { name: "Продукты" });
    await expect(productRegion.getByRole("link")).toHaveCount(2);
    for (const product of products) {
      await expect(productRegion.getByRole("link", { name: product.title, exact: true }))
        .toHaveAttribute("href", `/ru/products/${product.slug}`);
    }
    for (const readiness of readinessPanels) {
      const panel = main.getByRole("article", { name: readiness.title, exact: true });
      await expect(panel.getByText("Данные пока недоступны", { exact: true })).toBeVisible();
      await expect(panel.getByText(readiness.description, { exact: true })).toBeVisible();
      await expect(panel).not.toContainText(/\d|₽|€|\$/);
      await expect(panel.getByRole("progressbar")).toHaveCount(0);
      await expect(panel.getByRole("button")).toHaveCount(0);
      await expect(panel.getByRole("link")).toHaveCount(0);
    }
    await expect(main).not.toContainText(
      /нет\s+(?:активн[а-яё]+\s+)?(?:подписк|доступ)|(?:подписк[аи]|доступ)\s+(?:нет|отсутствует)|no\s+(?:subscription|access)/i
    );
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
  for (const product of products) {
    const card = main.getByRole("link", { name: new RegExp(product.title) });
    await card.scrollIntoViewIfNeeded();
    await expect(card).toBeInViewport();
    await expect(card.getByRole("heading", { name: product.name })).toBeVisible();
  }
  await expectMobileLayout(page, testInfo, "catalog");
  await main.getByRole("link", { name: new RegExp(products[0].title) }).click();
  await expect(page).toHaveURL(/\/ru\/products\/document-summary$/);
  const productTitle = main.getByRole("heading", { level: 1, name: products[0].title });
  await productTitle.scrollIntoViewIfNeeded();
  await expect(productTitle).toBeInViewport();
  await expect(main.getByText(products[0].description, { exact: true })).toBeVisible();
  await expectMobileLayout(page, testInfo, "product-detail");

  await main.getByRole("link", { name: "Войти или зарегистрироваться" }).click();
  await expect(page).toHaveURL(/\/ru\/account$/);
  await expect(main.getByRole("heading", { name: "Вход или регистрация" })).toBeVisible();
  await main.getByLabel("Email").fill("mobile-portal@example.com");
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
