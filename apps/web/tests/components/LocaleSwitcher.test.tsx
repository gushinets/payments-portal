import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import legalManifest from "@/generated/legal-manifest.json";
import {
  DISPLAY_NAME_BY_ROUTE_LOCALE,
  SUPPORTED_ROUTE_LOCALES
} from "@/generated/locales";
import {
  isLocaleSwitchingBlockedPathname,
  LocaleSwitcher
} from "@/shared/ui/LocaleSwitcher";

const sessionStorageKey = "anytoolai_session_token_v1";

describe("LocaleSwitcher", () => {
  it("preserves the stable pathname, query and session across seven locale destinations", async () => {
    const user = userEvent.setup();
    globalThis.__NEXT_INTL_PATHNAME__ = "/products";
    globalThis.__NEXT_SEARCH_PARAMS__ = "source=campaign&filter=active";
    window.localStorage.setItem(sessionStorageKey, "session-token");

    const { container } = render(<LocaleSwitcher locale="de" />);
    const summary = container.querySelector("summary");
    expect(summary).not.toBeNull();
    await user.click(summary!);

    const navigation = screen.getByRole("navigation", {
      name: "Выбор языка"
    });
    const destinations = within(navigation).getAllByRole("link");
    expect(destinations).toHaveLength(SUPPORTED_ROUTE_LOCALES.length);

    for (const [index, locale] of SUPPORTED_ROUTE_LOCALES.entries()) {
      expect(destinations[index]).toHaveTextContent(
        DISPLAY_NAME_BY_ROUTE_LOCALE[locale]
      );
      expect(destinations[index]).toHaveAttribute(
        "href",
        `/${locale}/products?source=campaign&filter=active`
      );
    }

    const frenchDestination = within(navigation).getByRole("link", {
      name: DISPLAY_NAME_BY_ROUTE_LOCALE.fr
    });
    frenchDestination.addEventListener("click", (event) =>
      event.preventDefault()
    );
    await user.click(frenchDestination);

    expect(window.localStorage.getItem(sessionStorageKey)).toBe(
      "session-token"
    );
  });

  it("blocks switching on reset confirmation and every generated legal pathname", () => {
    expect(isLocaleSwitchingBlockedPathname("/reset-password")).toBe(true);

    for (const document of legalManifest.documents) {
      expect(
        isLocaleSwitchingBlockedPathname(
          document.urlPath.replace(`/${legalManifest.region}`, "")
        )
      ).toBe(true);
    }

    expect(isLocaleSwitchingBlockedPathname("/forgot-password")).toBe(false);
  });
});
