import { expect, test } from "@playwright/test";
import {
  DISPLAY_NAME_BY_ROUTE_LOCALE,
  SUPPORTED_ROUTE_LOCALES
} from "../src/generated/locales";

const localeLanguages = [
  ["en", "en"],
  ["fr", "fr"],
  ["it", "it"],
  ["de", "de"],
  ["es", "es"],
  ["ru", "ru"],
  ["pt", "pt-BR"]
] as const;
const localePresentation = [
  ["en", "Products", "Products and plans"],
  ["fr", "Produits", "Produits et offres"],
  ["it", "Prodotti", "Prodotti e piani"],
  ["de", "Produkte", "Produkte und Tarife"],
  ["es", "Productos", "Productos y planes"],
  ["ru", "Продукты", "Продукты и тарифы"],
  ["pt", "Produtos", "Produtos e planos"]
] as const;
const metadataCases = [
  {
    locale: "de",
    title: "AnytoolAI — Digitale Dienste",
    description:
      "Digitale Dienste von AnytoolAI für die Arbeit mit Dokumenten, Inhalten und KI-Werkzeugen."
  },
  {
    locale: "pt",
    title: "AnytoolAI — Serviços digitais",
    description:
      "Serviços digitais da AnytoolAI para trabalhar com documentos, conteúdo e ferramentas de IA."
  }
] as const;
const legalSlugs = [
  "privacy",
  "consent-personal-data",
  "offer",
  "cancellation",
  "cookies",
  "security"
] as const;

function publicUrl(pathname: string): string {
  const publicBaseUrl = process.env.APP_PUBLIC_BASE_URL;

  if (!publicBaseUrl) {
    throw new Error("APP_PUBLIC_BASE_URL is required for locale routing tests");
  }

  return new URL(pathname, publicBaseUrl).href;
}

test("all supported locale roots render with their canonical document language", async ({
  page
}) => {
  expect(SUPPORTED_ROUTE_LOCALES).toEqual(
    localeLanguages.map(([locale]) => locale)
  );

  for (const [locale, languageTag] of localeLanguages) {
    const response = await page.goto(`/${locale}`);

    expect(response?.status()).toBe(200);
    await expect(page.locator("html")).toHaveAttribute("lang", languageTag);
  }
});

test("only the root negotiates Accept-Language and does not persist a locale cookie", async ({
  request
}) => {
  const cases = [
    ["de-AT,de;q=0.9", "/de"],
    ["pt-BR,pt;q=0.9", "/pt"],
    ["pt-PT,pt;q=0.9", "/pt"],
    ["ja-JP", "/ru"],
    ["", "/ru"]
  ] as const;

  for (const [acceptLanguage, expectedPath] of cases) {
    const response = await request.get("/", {
      headers: { "Accept-Language": acceptLanguage },
      maxRedirects: 0
    });

    expect(response.status()).toBe(307);
    expect(
      new URL(response.headers().location, publicUrl("/")).pathname
    ).toBe(expectedPath);
    expect(response.headers()["set-cookie"]).toBeUndefined();
  }
});

test("root locale negotiation preserves query parameters", async ({ request }) => {
  const response = await request.get(
    "/?source=campaign&return_to=/account",
    {
      headers: { "Accept-Language": "de-AT,de;q=0.9" },
      maxRedirects: 0
    }
  );
  const location = new URL(response.headers().location, publicUrl("/"));

  expect(response.status()).toBe(307);
  expect(location.pathname).toBe("/de");
  expect([...location.searchParams]).toEqual([
    ["source", "campaign"],
    ["return_to", "/account"]
  ]);
});

test("explicit locale routes win and arbitrary unprefixed paths stay not-found", async ({
  page
}) => {
  await page.setExtraHTTPHeaders({ "Accept-Language": "de-AT" });

  let response = await page.goto("/en");
  expect(response?.status()).toBe(200);
  expect(new URL(page.url()).pathname).toBe("/en");

  response = await page.goto("/pt/products");
  expect(response?.status()).toBe(200);
  expect(new URL(page.url()).pathname).toBe("/pt/products");
  await expect(page.locator("html")).toHaveAttribute("lang", "pt-BR");

  response = await page.goto("/products");
  expect(response?.status()).toBe(404);

  response = await page.goto("/unknown/products");
  expect(response?.status()).toBe(404);
});

test("representative localized metadata uses the public origin and canonical language tags", async ({
  page
}) => {
  for (const metadataCase of metadataCases) {
    await page.goto(`/${metadataCase.locale}/products`);

    await expect(page).toHaveTitle(metadataCase.title);
    await expect(page.locator('meta[name="description"]')).toHaveAttribute(
      "content",
      metadataCase.description
    );
    await expect(page.locator('link[rel="canonical"]')).toHaveAttribute(
      "href",
      publicUrl(`/${metadataCase.locale}/products`)
    );

    const alternateLinks = page.locator('link[rel="alternate"][hreflang]');
    await expect(alternateLinks).toHaveCount(localeLanguages.length);

    for (const [locale, languageTag] of localeLanguages) {
      await expect(
        page.locator(`link[rel="alternate"][hreflang="${languageTag}"]`)
      ).toHaveAttribute("href", publicUrl(`/${locale}/products`));
    }
  }
});

test("ordinary navigation keeps the active locale", async ({ page }) => {
  await page.goto("/de");

  await expect(page.getByRole("link", { name: "AnytoolAI" })).toHaveAttribute(
    "href",
    "/de"
  );
  await expect(page.getByRole("link", { name: "Produkte" })).toHaveAttribute(
    "href",
    "/de/products"
  );
  await expect(
    page.getByRole("main").getByRole("link", {
      name: "Anmelden oder registrieren"
    }).first()
  ).toHaveAttribute("href", "/de/auth-checkout");

  await page.getByRole("button", { name: "Anmelden" }).click();
  await expect(
    page
      .getByRole("dialog")
      .getByRole("link", { name: "Passwort vergessen?" })
  ).toHaveAttribute("href", "/de/forgot-password");
});

test("canonical RU footer labels retain Russian language metadata on non-RU routes", async ({
  page
}) => {
  await page.goto("/de");

  const legalLinks = page.locator(".footer-links a");
  await expect(legalLinks).toHaveCount(legalSlugs.length);

  for (const legalLink of await legalLinks.all()) {
    await expect(legalLink).toHaveAttribute("lang", "ru");
  }
});

test("source-owned seller facts retain Russian language metadata on non-RU routes", async ({
  page
}) => {
  await page.goto("/de");

  await expect(
    page.locator("footer").getByText("ИП Говоров Роман Стальевич", {
      exact: true
    })
  ).toHaveAttribute("lang", "ru");
  await expect(
    page.locator("footer").getByText(
      "630091 , Новосибирская область, г. Новосибирск",
      { exact: true }
    )
  ).toHaveAttribute("lang", "ru");
});

test("locale switching preserves pathname, query and auth storage across seven destinations", async ({
  context,
  page
}) => {
  const sessionStorageKey = "anytoolai_session_token_v1";
  const sessionToken = "locale-switch-session-token";

  await page.route("**/api/auth/session", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        authenticated: true,
        user: {
          tenant_id: "anytoolai",
          region: "ru",
          user_id: "locale-switch-user",
          email: "locale-switch@example.com",
          email_verified: true
        }
      })
    });
  });
  await page.goto("/de/products?source=campaign&filter=active");
  await page.evaluate(
    ({ key, token }) => {
      window.localStorage.setItem(key, token);
      window.dispatchEvent(new Event("anytoolai_session_changed"));
    },
    { key: sessionStorageKey, token: sessionToken }
  );
  await expect(page.getByText("locale-switch@example.com")).toBeVisible();
  await page.getByLabel(/Sprache wählen\. Aktuelle Sprache:/).click();

  const switcher = page.getByRole("navigation", { name: "Sprache wählen" });
  const destinations = switcher.getByRole("link");
  await expect(destinations).toHaveCount(SUPPORTED_ROUTE_LOCALES.length);

  for (const locale of SUPPORTED_ROUTE_LOCALES) {
    const destination = switcher.getByRole("link", {
      name: DISPLAY_NAME_BY_ROUTE_LOCALE[locale]
    });
    const href = await destination.getAttribute("href");
    expect(href).not.toBeNull();
    const url = new URL(href!, publicUrl("/"));

    expect(url.pathname).toBe(`/${locale}/products`);
    expect(url.searchParams.get("source")).toBe("campaign");
    expect(url.searchParams.get("filter")).toBe("active");
  }

  await switcher
    .getByRole("link", { name: DISPLAY_NAME_BY_ROUTE_LOCALE.fr })
    .click();
  await expect(page).toHaveURL(
    /\/fr\/products\?source=campaign&filter=active$/
  );
  await expect(page.getByText("locale-switch@example.com")).toBeVisible();
  expect(
    await page.evaluate(
      (key) => window.localStorage.getItem(key),
      sessionStorageKey
    )
  ).toBe(sessionToken);
  expect(await page.evaluate(() => Object.keys(window.localStorage))).toEqual([
    sessionStorageKey
  ]);
  expect(
    (await context.cookies()).some((cookie) =>
      /^(?:NEXT_LOCALE|.*locale.*)$/i.test(cookie.name)
    )
  ).toBe(false);
});

test("legal documents remain canonical RU-only routes without locale alternates", async ({
  page
}) => {
  for (const legalSlug of legalSlugs) {
    let response = await page.goto(`/ru/${legalSlug}`);
    expect(response?.status()).toBe(200);
    await expect(page.locator(".locale-switcher")).toHaveCount(0);
    await expect(page.locator("main section[lang=ru]")).toHaveCount(1);
    await expect(
      page.getByText(
        "Каноническая версия юридического документа представлена на русском языке."
      )
    ).toBeVisible();

    response = await page.goto(`/en/${legalSlug}`);
    expect(response?.status()).toBe(404);
  }

  await page.goto("/ru/privacy");
  await expect(page.locator('link[rel="canonical"]')).toHaveAttribute(
    "href",
    publicUrl("/ru/privacy")
  );
  await expect(
    page.locator('link[rel="alternate"][hreflang]')
  ).toHaveCount(0);
});

test("all seven locales render representative shell and catalog content", async ({
  page
}) => {
  expect(SUPPORTED_ROUTE_LOCALES).toEqual(
    localePresentation.map(([locale]) => locale)
  );

  for (const [locale, productsLabel, catalogTitle] of localePresentation) {
    const response = await page.goto(`/${locale}/products`);

    expect(response?.status()).toBe(200);
    await expect(
      page.getByRole("navigation").getByRole("link", {
        name: productsLabel,
        exact: true
      })
    ).toHaveAttribute("href", `/${locale}/products`);
    await expect(
      page.getByRole("heading", { name: catalogTitle, exact: true })
    ).toBeVisible();
  }
});
