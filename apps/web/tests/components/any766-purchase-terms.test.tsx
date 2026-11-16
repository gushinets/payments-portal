import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { NextIntlClientProvider } from "next-intl";
import { ProductBilling } from "@/features/billing/ProductBilling";
import { PurchaseTerms } from "@/features/billing/PurchaseTerms";
import type { PurchaseReviewResponse } from "@/generated/api-contracts/types.gen";
import ru from "@/messages/ru.json";
import { sessionStorageKey } from "@/shared/api/auth";
import { purchaseReview, purchaseUser, savedPurchase } from "../fixtures/purchase";
import { renderWithIntl } from "../setup/render-with-intl";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

function review(quantity: number): PurchaseReviewResponse {
  return {
    ...purchaseReview,
    technical_terms: {
      ...purchaseReview.technical_terms!, provenance: "CONFIGURED_SOURCE", source_version: "product-link-v3",
      offer: { product_id: "proposal_ai", metric_key: "proposal_ai.generations", unit: "generation", quantity, quantity_mode: "fixed_per_cycle" },
    },
  };
}

it.each([0, 7, Number.MAX_SAFE_INTEGER])("shows the exact configured quantity %s and unit independently of commercial quantity", (quantity) => {
  renderWithIntl(<PurchaseTerms review={review(quantity)} />, { locale: "ru", messages: ru });
  const technical = within(screen.getByText(ru.Purchase.technicalLimit).parentElement!);
  expect(technical.getByText(`${quantity.toLocaleString("ru-RU")} generation`.replaceAll("\u00a0", " "))).toBeVisible();
  expect(technical.getByText("proposal_ai.generations")).toBeVisible();
  expect(screen.queryByText(ru.Purchase.simulatedTerms)).not.toBeInTheDocument();
  const commercial = within(screen.getByText(ru.CatalogPreview.quantity).parentElement!);
  expect(commercial.getByText("1")).toBeVisible();
  expect(document.body).not.toHaveTextContent(/unlimited|безлимит/i);
});

it("keeps simulated history labelled and legacy technical quantity unknown", () => {
  const view = renderWithIntl(<PurchaseTerms review={purchaseReview} />, { locale: "ru", messages: ru });
  expect(screen.getByText(ru.Purchase.simulatedTerms)).toBeVisible();
  view.rerender(<NextIntlClientProvider locale="ru" messages={ru}><PurchaseTerms review={{ ...purchaseReview, technical_terms: null, expected_technical_terms_digest: null }} /></NextIntlClientProvider>);
  expect(screen.getByText(ru.Purchase.technicalUnknown)).toBeVisible();
  expect(screen.queryByText(ru.Purchase.simulatedTerms)).not.toBeInTheDocument();
  expect(screen.queryByText("100 generation")).not.toBeInTheDocument();
});

it("updates selected quantity before a new consent while retaining the original review object", () => {
  const original = review(7);
  const view = renderWithIntl(<PurchaseTerms review={original} />, { locale: "ru", messages: ru });
  expect(screen.getByText("7 generation")).toBeVisible();
  view.rerender(<NextIntlClientProvider locale="ru" messages={ru}><PurchaseTerms review={review(8)} /></NextIntlClientProvider>);
  expect(screen.getByText("8 generation")).toBeVisible();
  expect(screen.queryByText("7 generation")).not.toBeInTheDocument();
  expect(original.technical_terms!.offer.quantity).toBe(7);
});

it("shows configured terms before consent and requires unchecked consent again after a quantity change", async () => {
  window.localStorage.setItem(sessionStorageKey, "synthetic-session");
  let currentReview = review(7);
  const confirmations: unknown[] = [];
  vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input, init) => {
    const path = new URL(String(input)).pathname;
    if (path === "/api/purchase-intents/current") return Response.json({ purchase: null });
    if (path === "/api/purchases/review") return Response.json(currentReview);
    if (path === "/api/purchase-intents") {
      confirmations.push(JSON.parse(String(init?.body)));
      if (confirmations.length === 1) {
        currentReview = { ...review(8), revision_id: "66666666-6666-4666-8666-666666666666", expected_technical_terms_digest: "sha256:" + "f".repeat(64) };
        return Response.json({ detail: { code: "terms_changed" } }, { status: 409 });
      }
      return Response.json({ ...savedPurchase, accepted: currentReview, state: "created" });
    }
    if (path.endsWith("/advance")) return Response.json({ ...savedPurchase, accepted: currentReview });
    throw new Error("unexpected_synthetic_request");
  }));
  renderWithIntl(<ProductBilling productId="proposal_ai" offerAvailable user={purchaseUser} />, { locale: "ru", messages: ru });
  fireEvent.click(await screen.findByRole("button", { name: ru.Purchase.buy }));
  expect(await screen.findByText("7 generation")).toBeVisible();
  expect(screen.queryByText(ru.Purchase.simulatedTerms)).not.toBeInTheDocument();
  expect(screen.getByRole("checkbox")).not.toBeChecked();
  expect(screen.getByRole("button", { name: ru.Purchase.confirm })).toBeDisabled();
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: ru.Purchase.confirm }));
  expect(await screen.findByRole("alert")).toHaveTextContent(ru.Billing.errors.termsChanged);
  fireEvent.click(screen.getByRole("button", { name: ru.Purchase.buy }));
  expect(await screen.findByText("8 generation")).toBeVisible();
  expect(screen.getByRole("checkbox")).not.toBeChecked();
  expect(screen.getByRole("button", { name: ru.Purchase.confirm })).toBeDisabled();
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: ru.Purchase.confirm }));
  expect(await screen.findByRole("link", { name: ru.Purchase.manage })).toBeVisible();
  expect(confirmations).toHaveLength(2);
  expect(confirmations[1]).toMatchObject({ revision_id: currentReview.revision_id, expected_technical_terms_digest: currentReview.expected_technical_terms_digest });
});
