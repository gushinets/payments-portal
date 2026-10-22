import { act, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CatalogPreviewClient } from "@/features/catalog/CatalogPreviewClient";
import { formatCatalogMoney } from "@/features/catalog/format-money";
import en from "@/messages/en.json";
import ru from "@/messages/ru.json";
import fr from "@/messages/fr.json";
import de from "@/messages/de.json";
import itMessages from "@/messages/it.json";
import es from "@/messages/es.json";
import pt from "@/messages/pt.json";
import { simulatedProduct } from "../fixtures/catalog";
import { renderWithIntl } from "../setup/render-with-intl";

const fetchMock = vi.fn<typeof fetch>();

describe("stored catalog preview", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => vi.unstubAllGlobals());

  it.each([
    ["en", en], ["ru", ru], ["fr", fr], ["de", de], ["it", itMessages], ["es", es], ["pt", pt]
  ] as const)("discloses simulation and renders source identity in %s", async (locale, messages) => {
    fetchMock.mockResolvedValueOnce(Response.json({ products: [simulatedProduct] }));
    renderWithIntl(<CatalogPreviewClient />, { locale, messages: { CatalogPreview: messages.CatalogPreview } });
    expect(await screen.findByText(messages.CatalogPreview.simulated)).toBeVisible();
    expect(screen.getByText("proposal_ai")).toBeVisible();
    expect(screen.getByRole("link", { name: messages.CatalogPreview.details }))
      .toHaveAttribute("href", `/${locale}/products/proposal_ai`);
    expect(screen.getByText(messages.CatalogPreview.previewNote)).toBeVisible();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it.each([
    ["en", en, "1 month"], ["ru", ru, "1 месяц"], ["fr", fr, "1 mois"], ["de", de, "1 Monat"],
    ["it", itMessages, "1 mese"], ["es", es, "1 mes"], ["pt", pt, "1 mês"]
  ] as const)("distinguishes all period anchors for the same duration in %s", async (locale, messages, duration) => {
    const offer = simulatedProduct.offer;
    if (!offer) throw new Error("simulated fixture requires offer");
    const anchors = ["calendar_month", "instance_start", "first_instance_start"] as const;
    const products = anchors.map((anchor) => ({
      ...simulatedProduct,
      product_id: `proposal_ai_${anchor}`,
      offer: { ...offer, period: { ...offer.period, anchor } }
    }));
    fetchMock.mockResolvedValueOnce(Response.json({ products }));
    renderWithIntl(<CatalogPreviewClient />, { locale, messages: { CatalogPreview: messages.CatalogPreview } });

    const cards = await screen.findAllByRole("article");
    expect(cards).toHaveLength(anchors.length);
    expect(new Set(Object.values(messages.CatalogPreview.periodAnchors)).size).toBe(anchors.length);
    for (const [index, anchor] of anchors.entries()) {
      const card = within(cards[index]);
      expect(card.getByText(messages.CatalogPreview.periodAnchors[anchor])).toBeVisible();
      expect(card.getByText(messages.CatalogPreview.periodAnchors[anchor]).closest("dd"))
        .toHaveTextContent(duration);
      for (const other of anchors.filter((value) => value !== anchor)) {
        expect(card.queryByText(messages.CatalogPreview.periodAnchors[other])).not.toBeInTheDocument();
      }
    }
  });

  it("keeps exact money beyond Number precision in Brazilian Portuguese", async () => {
    fetchMock.mockResolvedValueOnce(Response.json(simulatedProduct));
    renderWithIntl(<CatalogPreviewClient productId="proposal_ai" />, {
      locale: "pt", messages: { CatalogPreview: pt.CatalogPreview }
    });
    expect(await screen.findByText("9.007.199.254.740.993,01 RUB")).toBeVisible();
    expect(screen.getByText("7,03 RUB")).toBeVisible();
    const period = screen.getByText("1 mês").closest("dd");
    expect(period).toHaveTextContent("1 mês");
    expect(period).toHaveTextContent(pt.CatalogPreview.periodAnchors.instance_start);
    expect(screen.getByText("25 generation")).toBeVisible();
  });

  it("shows honest approved-but-unverified state without a purchase action", async () => {
    const offer = simulatedProduct.offer;
    if (!offer) throw new Error("simulated fixture requires offer");
    fetchMock.mockResolvedValueOnce(Response.json({
      ...simulatedProduct, availability: "APPROVED_UNVERIFIED_NOW", evidence_mode: "GENUINE",
      offer: { ...offer, evidence_mode: "GENUINE", publication_state: "PUBLISHED_APPROVED_UNVERIFIED_NOW" }
    }));
    renderWithIntl(<CatalogPreviewClient productId="proposal_ai" />, {
      locale: "en", messages: { CatalogPreview: en.CatalogPreview }
    });
    expect(await screen.findByText(en.CatalogPreview.unverified)).toBeVisible();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it.each([
    [{ products: [] }, 200, en.CatalogPreview.empty],
    [{ detail: { code: "catalog_product_not_found" } }, 404, en.CatalogPreview.notFound],
    [{ detail: { code: "catalog_unavailable" } }, 503, en.CatalogPreview.failed],
    [{ detail: { code: "internal_server_error" } }, 500, en.CatalogPreview.failed],
    [{ product_id: "proposal_ai", evidence_mode: "SIMULATED", availability: "UNAVAILABLE_AMBIGUOUS_OFFERS", offer: null }, 200, en.CatalogPreview.ambiguous]
  ] as const)("distinguishes empty, absent, ambiguous and failure states", async (payload, status, text) => {
    fetchMock.mockResolvedValueOnce(Response.json(payload, { status }));
    renderWithIntl(<CatalogPreviewClient productId={"products" in payload ? undefined : "proposal_ai"} />, {
      locale: "en", messages: { CatalogPreview: en.CatalogPreview }
    });
    expect(await screen.findByText(text)).toBeVisible();
    expect(screen.queryByText(/RUB/)).not.toBeInTheDocument();
  });

  it("shows loading, then recovers from API failure with explicit retry", async () => {
    fetchMock.mockResolvedValueOnce(new Response("invalid JSON", { status: 200 }))
      .mockResolvedValueOnce(Response.json({ products: [simulatedProduct] }));
    renderWithIntl(<CatalogPreviewClient />, { locale: "en", messages: { CatalogPreview: en.CatalogPreview } });
    expect(screen.getByRole("status")).toHaveTextContent(en.CatalogPreview.loading);
    fireEvent.click(await screen.findByRole("button", { name: en.CatalogPreview.retry }));
    expect(await screen.findByText(en.CatalogPreview.simulated)).toBeVisible();
  });

  it("ignores a response after unmount", async () => {
    let complete: (response: Response) => void = () => undefined;
    fetchMock.mockReturnValueOnce(new Promise((resolve) => { complete = resolve; }));
    const view = renderWithIntl(<CatalogPreviewClient productId="proposal_ai" />, {
      locale: "en", messages: { CatalogPreview: en.CatalogPreview }
    });
    view.unmount();
    await act(async () => complete(Response.json(simulatedProduct)));
    expect(screen.queryByText("proposal_ai")).not.toBeInTheDocument();
  });
});

describe("exact display formatting", () => {
  it("preserves arbitrary supported scale and uses localized separators", () => {
    expect(formatCatalogMoney("9007199254740993.123456789012345678", "RUB", "en"))
      .toBe("9,007,199,254,740,993.123456789012345678\u00a0RUB");
    expect(formatCatalogMoney("7.0300", "RUB", "ru")).toBe("7,0300\u00a0RUB");
    expect(formatCatalogMoney("7", "RUB", "pt-BR")).toBe("7\u00a0RUB");
  });
});
