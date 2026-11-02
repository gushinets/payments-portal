// Opt-in normal-connection acceptance, replacing the historical v1 file workflow.
import { readFileSync } from "node:fs";
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import type { CatalogProductResponse, CatalogProductsResponse } from "../src/generated/api-contracts/types.gen";
import { formatCatalogMoney } from "../src/features/catalog/format-money";
import ru from "../src/messages/ru.json";

test("ANY-709 Step 1 normal connection serves discovery and a live selected offer", async ({ page, request }, testInfo) => {
  test.skip(process.env.CATALOG_PREVIEW_ACCEPTANCE !== "1", "Human-configured connection and publication required");
  const publicationPath = process.env.CATALOG_PREVIEW_PUBLICATION_FILE;
  expect(publicationPath).toBeTruthy();
  const publication = JSON.parse(readFileSync(publicationPath!, "utf8")) as {
    mapping_revision_id: string;
    document: { schema_version: string; selection: { product_id: string } };
  };
  expect(publication.document.schema_version).toBe("product-link-v2");
  const productId = publication.document.selection.product_id;
  const list = await request.get("/api/catalog/products");
  expect(list.ok()).toBe(true);
  expect(list.headers()["cache-control"]).toBe("no-store");
  const products = await list.json() as CatalogProductsResponse;
  expect(products.products.find((product) => product.product_id === productId))
    .toMatchObject({ availability: "DETAILS_REQUIRED", offer: null });
  const detail = await request.get(`/api/catalog/products/${encodeURIComponent(productId)}`);
  expect(detail.ok()).toBe(true);
  expect(detail.headers()["cache-control"]).toBe("no-store");
  const product = await detail.json() as CatalogProductResponse;
  expect(product.availability).toBe("CURRENT_OFFER");
  expect(product.offer?.revision_id).toBe(publication.mapping_revision_id);
  expect(product.offer?.billing_provenance).toBe("CONFIGURED_SOURCE");
  if (!product.offer) throw new Error("Current offer required");

  await page.goto(`/ru/products/${encodeURIComponent(productId)}`);
  const main = page.getByRole("main");
  await expect(main.getByText(productId, { exact: true }).last()).toBeVisible();
  await expect(main.getByText(ru.CatalogPreview.unverified)).toBeVisible();
  await expect(main.getByText(formatCatalogMoney(product.offer.money.recurring_amount,
    product.offer.money.currency, "ru"), { exact: true })).toBeVisible();
  await expect(main.getByText(ru.CatalogPreview.quantity).locator("..")).toContainText(product.offer.commercial_quantity);
  await expect(main.getByText(ru.CatalogPreview.allowance)).toHaveCount(0);
  await expect(main.getByRole("progressbar")).toHaveCount(0);
  await page.getByRole("button", { name: ru.CookieBanner.acceptAction, exact: true }).click();
  expect((await new AxeBuilder({ page }).analyze()).violations
    .filter(({ impact }) => impact === "serious" || impact === "critical")).toEqual([]);
  await testInfo.attach("any709-step1-current-offer", { body: await page.screenshot({ fullPage: true }), contentType: "image/png" });
  await page.reload();
  await expect(main.getByText(ru.CatalogPreview.unverified)).toBeVisible();
});
