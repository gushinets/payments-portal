import { expect, test } from "@playwright/test";

const localeLanguages = [
  ["en", "en"],
  ["fr", "fr"],
  ["it", "it"],
  ["de", "de"],
  ["es", "es"],
  ["ru", "ru"],
  ["pt", "pt-BR"]
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

test("ordinary locale metadata uses the configured public origin and canonical language tags", async ({
  page
}) => {
  await page.goto("/de/products");

  await expect(page.locator('link[rel="canonical"]')).toHaveAttribute(
    "href",
    publicUrl("/de/products")
  );

  const alternateLinks = page.locator('link[rel="alternate"][hreflang]');
  await expect(alternateLinks).toHaveCount(localeLanguages.length);

  for (const [locale, languageTag] of localeLanguages) {
    await expect(
      page.locator(`link[rel="alternate"][hreflang="${languageTag}"]`)
    ).toHaveAttribute("href", publicUrl(`/${locale}/products`));
  }
});

test("legal documents remain canonical RU-only routes without locale alternates", async ({
  page
}) => {
  for (const legalSlug of legalSlugs) {
    let response = await page.goto(`/ru/${legalSlug}`);
    expect(response?.status()).toBe(200);

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

test("representative localized content is present in the server response", async ({
  request
}) => {
  const response = await request.get("/de/products");

  expect(response.status()).toBe(200);
  expect(await response.text()).toContain("Продукты и тарифы");
});
