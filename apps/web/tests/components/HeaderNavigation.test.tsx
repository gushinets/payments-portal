import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SUPPORTED_ROUTE_LOCALES } from "@/generated/locales";
import deMessages from "@/messages/de.json";
import enMessages from "@/messages/en.json";
import esMessages from "@/messages/es.json";
import frMessages from "@/messages/fr.json";
import itMessages from "@/messages/it.json";
import ptMessages from "@/messages/pt.json";
import ruMessages from "@/messages/ru.json";
import { HeaderNavigation } from "@/shared/ui/HeaderNavigation";
import { renderWithIntl } from "../setup/render-with-intl";

const messageCatalogs = {
  de: deMessages,
  en: enMessages,
  es: esMessages,
  fr: frMessages,
  it: itMessages,
  pt: ptMessages,
  ru: ruMessages
};

describe("HeaderNavigation", () => {
  it.each(SUPPORTED_ROUTE_LOCALES)(
    "renders only localized Products and Pricing links in %s",
    (locale) => {
      const messages = messageCatalogs[locale];
      globalThis.__NEXT_INTL_PATHNAME__ = "/pricing";
      renderWithIntl(<HeaderNavigation />, {
        locale,
        messages: { Navigation: messages.Navigation }
      });

      expect(screen.getAllByRole("link")).toHaveLength(2);
      const pricingLink = screen.getByRole("link", {
        name: messages.Navigation.pricing
      });
      const productsLink = screen.getByRole("link", {
        name: messages.Navigation.products
      });
      expect(pricingLink).toHaveAttribute("href", `/${locale}/pricing`);
      expect(pricingLink).toHaveAttribute("aria-current", "page");
      expect(productsLink).toHaveAttribute("href", `/${locale}/products`);
      expect(productsLink).not.toHaveAttribute("aria-current");
    }
  );

  it.each([
    ["/products", "page"],
    ["/products/document-summary", "location"],
    ["/products/prompt-optimizer", "location"]
  ])("keeps the product section active on %s", (pathname, current) => {
    globalThis.__NEXT_INTL_PATHNAME__ = pathname;
    renderWithIntl(<HeaderNavigation />, {
      locale: "ru",
      messages: { Navigation: ruMessages.Navigation }
    });

    const productsLink = screen.getByRole("link", { name: "AI-утилиты" });
    expect(productsLink).toHaveAttribute("href", "/ru/products");
    expect(productsLink).toHaveAttribute("aria-current", current);
    expect(
      screen.getByRole("link", { name: "Тарифы" })
    ).not.toHaveAttribute("aria-current");
  });

  it.each(["/", "/account", "/products-archive", "/pricing-preview"])(
    "does not highlight another section on %s",
    (pathname) => {
      globalThis.__NEXT_INTL_PATHNAME__ = pathname;
      renderWithIntl(<HeaderNavigation />, {
        locale: "ru",
        messages: { Navigation: ruMessages.Navigation }
      });

      for (const link of screen.getAllByRole("link")) {
        expect(link).not.toHaveAttribute("aria-current");
      }
    }
  );
});
