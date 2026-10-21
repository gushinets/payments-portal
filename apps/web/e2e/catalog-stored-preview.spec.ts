import { readFile } from "node:fs/promises";

import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import type { CatalogProductResponse, CatalogProductsResponse } from "../src/generated/api-contracts/types.gen";
import ru from "../src/messages/ru.json";

// Manual Step 6 acceptance. No page.route(), response fixture, or DB seeding:
// compare every real HTTP response with the separately published DB revision.
test("stored SIMULATED offer reaches the browser through the real Portal API", async ({ page, request }, testInfo) => {
  test.skip(process.env.CATALOG_PREVIEW_ACCEPTANCE !== "1", "Requires explicit dev publication; see DEVELOPMENT.md");

  const apiBase = process.env.PLAYWRIGHT_API_BASE_URL;
  const publicationFile = process.env.CATALOG_PREVIEW_PUBLICATION_FILE;
  if (!apiBase || !publicationFile) {
    throw new Error("PLAYWRIGHT_API_BASE_URL and CATALOG_PREVIEW_PUBLICATION_FILE are required");
  }
  // Private operator audit artifact, separate from the generated Portal DTOs.
  const publication = JSON.parse(await readFile(publicationFile, "utf8")) as {
    mapping_revision_id: string;
    revision_number: number;
    stored_document: {
      evidence_mode: string;
      material: {
        technical: { product_id: string; allowance: number };
        terms: { money: { recurring_amount: string; connection_amount: string; currency: string } };
      };
    };
  };
  expect(publication.mapping_revision_id).toMatch(/^[0-9a-f-]{36}$/);
  expect(publication.stored_document.evidence_mode).toBe("SIMULATED");
  expect(publication.stored_document.material.technical).toMatchObject({ product_id: "proposal_ai", allowance: 25 });
  expect(publication.stored_document.material.terms.money).toMatchObject({
    recurring_amount: "200.02", connection_amount: "14.06", currency: "RUB"
  });

  const response = await request.get(`${apiBase}/api/catalog/products`);
  expect(response.status()).toBe(200);
  const payload: CatalogProductsResponse = await response.json();
  const product = payload.products.find((item) => item.product_id === "proposal_ai");
  expect(product).toBeDefined();
  expect(product?.availability).toBe("SIMULATED_PREVIEW");
  expect(product?.evidence_mode).toBe("SIMULATED");
  expect(product?.offer?.evidence_mode).toBe("SIMULATED");
  expect(product?.offer?.publication_state).toBe("SIMULATED");
  expect(product?.offer?.revision_id).toBe(publication.mapping_revision_id);
  expect(product?.offer?.revision_number).toBe(publication.revision_number);
  expect(product?.offer?.money.currency).toBe("RUB");
  expect(product?.offer?.money.recurring_amount).toBe("200.02");
  expect(product?.offer?.money.connection_amount).toBe("14.06");
  expect(product?.offer?.allowance.quantity).toBe("25");

  const catalogRequests: { authorization: string | undefined }[] = [];
  page.on("request", (outbound) => {
    if (new URL(outbound.url()).pathname.startsWith("/api/catalog/products")) {
      catalogRequests.push({ authorization: outbound.headers().authorization });
    }
  });
  const listResponse = page.waitForResponse((incoming) =>
    new URL(incoming.url()).pathname === "/api/catalog/products"
  );
  await page.goto("/ru/products");
  const listed = await listResponse;
  expect(listed.status()).toBe(200);
  const browserList: CatalogProductsResponse = await listed.json();
  expect(browserList.products.find((item) => item.product_id === "proposal_ai")).toEqual(product);
  const main = page.getByRole("main");
  const card = main.getByRole("article").filter({ has: page.getByText("proposal_ai", { exact: true }) });
  await expect(card.getByText(ru.CatalogPreview.simulated)).toBeVisible();
  await expect(card.getByText("200,02 RUB", { exact: true })).toBeVisible();
  await expect(card.getByText("14,06 RUB", { exact: true })).toBeVisible();
  await expect(card.getByText("25 generation", { exact: true })).toBeVisible();
  await testInfo.attach("catalog-list", { body: await page.screenshot({ fullPage: true }), contentType: "image/png" });

  const detailResponse = page.waitForResponse((incoming) =>
    new URL(incoming.url()).pathname === "/api/catalog/products/proposal_ai"
  );
  await card.getByRole("link", { name: ru.CatalogPreview.details }).click();
  await expect(page).toHaveURL(/\/ru\/products\/proposal_ai$/);
  const detailed = await detailResponse;
  expect(detailed.status()).toBe(200);
  const detail: CatalogProductResponse = await detailed.json();
  expect(detail).toEqual(product);
  await expect(main.getByText(ru.CatalogPreview.simulated)).toBeVisible();
  await expect(main.getByText("200,02 RUB", { exact: true })).toBeVisible();
  await expect(main.getByText("14,06 RUB", { exact: true })).toBeVisible();
  await expect(main.getByText("25 generation", { exact: true })).toBeVisible();
  await testInfo.attach("product-detail", { body: await page.screenshot({ fullPage: true }), contentType: "image/png" });

  const reloadedOffer = page.waitForResponse((incoming) =>
    new URL(incoming.url()).pathname === "/api/catalog/products/proposal_ai"
  );
  await page.reload();
  const reloadedResponse = await reloadedOffer;
  expect(reloadedResponse.status()).toBe(200);
  const reloadedProduct: CatalogProductResponse = await reloadedResponse.json();
  expect(reloadedProduct).toEqual(product);
  await expect(main.getByRole("heading", { name: ru.CatalogPreview.productTitle, level: 1 })).toBeVisible();
  await expect(main.getByText(ru.CatalogPreview.simulated)).toBeVisible();
  await expect(main.getByText("200,02 RUB", { exact: true })).toBeVisible();
  await expect(main.getByText("14,06 RUB", { exact: true })).toBeVisible();
  await expect(main.getByText("25 generation", { exact: true })).toBeVisible();
  await expect(main.getByRole("button")).toHaveCount(0);
  expect(catalogRequests.length).toBeGreaterThanOrEqual(3);
  expect(catalogRequests.every((outbound) => outbound.authorization === undefined)).toBe(true);
  await page.getByRole("button", { name: ru.CookieBanner.acceptAction, exact: true }).click();
  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(accessibility.violations.filter((violation) => ["critical", "serious"].includes(violation.impact ?? "")))
    .toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await testInfo.attach("real-api-stored-simulated-preview", {
    body: await page.screenshot({ fullPage: true }), contentType: "image/png"
  });
  await testInfo.attach("stored-revision", {
    body: JSON.stringify({ publication_revision_id: publication.mapping_revision_id, product, browserList, detail, reloadedProduct }),
    contentType: "application/json"
  });
});
