import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PurchaseReview } from "@/features/purchases/PurchaseReview";
import type { PurchaseReviewResponse } from "@/generated/api-contracts/types.gen";
import en from "@/messages/en.json";
import ru from "@/messages/ru.json";
import fr from "@/messages/fr.json";
import de from "@/messages/de.json";
import itMessages from "@/messages/it.json";
import es from "@/messages/es.json";
import pt from "@/messages/pt.json";
import { simulatedProduct } from "../fixtures/catalog";
import { renderWithIntl } from "../setup/render-with-intl";

describe("purchase consent period", () => {
  it.each([
    ["en", en, "1 month"], ["ru", ru, "1 месяц"], ["fr", fr, "1 mois"],
    ["de", de, "1 Monat"], ["it", itMessages, "1 mese"],
    ["es", es, "1 mes"], ["pt", pt, "1 mês"]
  ] as const)("shows each period anchor beside its duration in %s", (locale, messages, duration) => {
    const offer = simulatedProduct.offer;
    if (!offer) throw new Error("simulated fixture requires offer");
    const anchors = ["calendar_month", "instance_start", "first_instance_start"] as const;
    for (const anchor of anchors) {
      const review: PurchaseReviewResponse = {
        product_id: simulatedProduct.product_id,
        availability: "SIMULATED_PREVIEW",
        fingerprint: `sha256:${"a".repeat(64)}`,
        offer: { ...offer, period: { ...offer.period, anchor } },
        seller_name: "SIMULATED seller",
        initial_amount: "214.08",
        recurring_required: false,
        renewal_terms: "SIMULATED renewal",
        cancellation_terms: "SIMULATED cancellation",
        documents: []
      };
      const view = renderWithIntl(
        <PurchaseReview
          review={review}
          showConsent
          busy={false}
          commercial={false}
          recurring={false}
          documents={new Set<string>()}
          onCommercialChange={vi.fn()}
          onRecurringChange={vi.fn()}
          onDocumentChange={vi.fn()}
          onSubmit={vi.fn()}
        />,
        { locale, messages: { Purchase: messages.Purchase, CatalogPreview: messages.CatalogPreview } }
      );
      const rule = screen.getByText(messages.CatalogPreview.periodAnchors[anchor]);
      expect(rule).toBeVisible();
      expect(rule.closest("dd")).toHaveTextContent(duration);
      expect(screen.getByRole("button", { name: messages.Purchase.purchase })).toBeVisible();
      for (const other of anchors.filter((value) => value !== anchor)) {
        expect(screen.queryByText(messages.CatalogPreview.periodAnchors[other])).not.toBeInTheDocument();
      }
      view.unmount();
    }
  });
});
