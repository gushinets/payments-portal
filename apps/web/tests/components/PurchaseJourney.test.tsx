import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PurchaseJourneyClient } from "@/features/purchases/PurchaseJourneyClient";
import type { PurchaseReviewResponse } from "@/generated/api-contracts/types.gen";
import en from "@/messages/en.json";
import { sessionChangedEvent, sessionStorageKey } from "@/shared/api/auth";
import { simulatedProduct } from "../fixtures/catalog";
import { renderWithIntl } from "../setup/render-with-intl";

const fetchMock = vi.fn<typeof fetch>();
const user = {
  user_id: "11111111-1111-4111-8111-111111111111",
  tenant_id: "anytoolai",
  region: "ru",
  email: "test@example.invalid",
  email_verified: true
};
const intentId = "22222222-2222-4222-8222-222222222222";
const review: PurchaseReviewResponse = {
  product_id: "proposal_ai",
  availability: "SIMULATED_PREVIEW",
  fingerprint: "sha256:" + "a".repeat(64),
  offer: {
    ...simulatedProduct.offer!,
    money: {
      recurring_amount: "200.02",
      connection_amount: "14.06",
      currency: "RUB",
      decimal_places: 2,
      units: "major"
    }
  },
  seller_name: "SIMULATED seller",
  initial_amount: "214.08",
  recurring_required: false,
  renewal_terms: "SIMULATED renewal",
  cancellation_terms: "SIMULATED cancellation",
  documents: [
    {
      document_version_id: "33333333-3333-4333-8333-333333333333",
      legal_entity_id: "44444444-4444-4444-8444-444444444444",
      doc_type: "offer",
      version: "test-v1",
      title: "Тестовый документ",
      url_path: "/ru/offer",
      content_hash: "test-hash",
      acceptance_text: "Принимаю тестовые условия",
      acceptance_text_hash: "a".repeat(64)
    }
  ]
};
const json = (value: unknown) => Response.json(value);
const purchase = (linked = false) => ({
  purchase_intent_id: intentId,
  state: linked ? "linked" : "created",
  next_action: linked ? "manage" : "continue",
  continue_available: !linked,
  accepted_at: "2026-10-22T00:00:00Z",
  accepted_terms: review
});
function renderJourney() {
  return renderWithIntl(<PurchaseJourneyClient productId="proposal_ai" />, {
    locale: "en",
    messages: { Purchase: en.Purchase, CatalogPreview: en.CatalogPreview }
  });
}

describe("purchase operation and Widget lifetime", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
    window.localStorage.setItem(sessionStorageKey, "portal-session");
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => vi.unstubAllGlobals());

  it("shows signed-out state without a request and loads after session arrival", async () => {
    window.localStorage.removeItem(sessionStorageKey);
    fetchMock.mockImplementation(async (url) => {
      const path = new URL(String(url)).pathname;
      if (path === "/api/auth/session")
        return json({ authenticated: true, user });
      if (path.endsWith("/status"))
        return json({ state: "not_ready", purchase_intent_id: null });
      return json(review);
    });
    renderJourney();
    expect(
      screen.getByRole("link", { name: en.Purchase.signIn })
    ).toBeVisible();
    expect(fetchMock).not.toHaveBeenCalled();

    act(() => {
      window.localStorage.setItem(sessionStorageKey, "portal-session");
      window.dispatchEvent(new Event(sessionChangedEvent));
    });
    expect(
      await screen.findByRole("button", { name: en.Purchase.purchase })
    ).toBeVisible();
    expect(
      screen.queryByRole("link", { name: en.Purchase.signIn })
    ).not.toBeInTheDocument();
  });

  it("ignores an old session read after a newer session has loaded", async () => {
    let finishOld: (response: Response) => void = () => undefined;
    const oldSession = new Promise<Response>((done) => {
      finishOld = done;
    });
    fetchMock.mockImplementation(async (url, options) => {
      const path = new URL(String(url)).pathname;
      if (path === "/api/auth/session") {
        return new Headers(options?.headers).get("Authorization") ===
          "Bearer portal-session"
          ? oldSession
          : json({ authenticated: true, user });
      }
      if (path.endsWith("/status"))
        return json({ state: "not_ready", purchase_intent_id: null });
      return json(review);
    });
    renderJourney();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    act(() => {
      window.localStorage.setItem(sessionStorageKey, "new-portal-session");
      window.dispatchEvent(new Event(sessionChangedEvent));
    });
    await screen.findByRole("button", { name: en.Purchase.purchase });
    await act(async () =>
      finishOld(
        json({ authenticated: true, user: { ...user, email_verified: false } })
      )
    );
    expect(
      screen.getByRole("button", { name: en.Purchase.purchase })
    ).toBeVisible();
    expect(screen.queryByText(en.Purchase.ineligible)).not.toBeInTheDocument();
  });

  it("keeps one attempt key across double submit and uncertain network retry", async () => {
    let accepted = false;
    let creates = 0;
    const keys: string[] = [];
    fetchMock.mockImplementation(async (url, options) => {
      const path = new URL(String(url)).pathname;
      if (path === "/api/auth/session")
        return json({ authenticated: true, user });
      if (path.endsWith("/status"))
        return json({
          state: accepted ? "preparing" : "not_ready",
          purchase_intent_id: accepted ? intentId : null
        });
      if (path.includes("/review/")) return json(review);
      if (path === "/api/purchases") {
        creates += 1;
        keys.push(new Headers(options?.headers).get("Idempotency-Key")!);
        if (creates === 1) throw new TypeError("lost reply");
        accepted = true;
        return json(purchase());
      }
      return json(purchase());
    });
    renderJourney();
    await screen.findByRole("button", { name: en.Purchase.purchase });
    screen.getAllByRole("checkbox").forEach((node) => fireEvent.click(node));
    const form = screen
      .getByRole("button", { name: en.Purchase.purchase })
      .closest("form")!;
    fireEvent.submit(form);
    fireEvent.submit(form);
    await screen.findByText(en.Purchase.states.uncertain);
    expect(creates).toBe(1);
    fireEvent.click(screen.getByRole("button", { name: en.Purchase.refresh }));
    await screen.findByRole("button", { name: en.Purchase.purchase });
    fireEvent.submit(
      screen
        .getByRole("button", { name: en.Purchase.purchase })
        .closest("form")!
    );
    await screen.findByRole("button", { name: en.Purchase.continue });
    expect(keys).toHaveLength(2);
    expect(keys[0]).toBe(keys[1]);
  });

  it.each(["same-tab", "cross-tab", "unmount"])(
    "discards a late bootstrap on %s session disposal",
    async (event) => {
      let resolve: (response: Response) => void = () => undefined;
      const pending = new Promise<Response>((done) => {
        resolve = done;
      });
      fetchMock.mockImplementation(async (url) => {
        const path = new URL(String(url)).pathname;
        if (path === "/api/auth/session")
          return json({ authenticated: true, user });
        if (path.endsWith("/status"))
          return json({ state: "manage", purchase_intent_id: intentId });
        if (path.endsWith("/widget-bootstrap")) return pending;
        return json(purchase(true));
      });
      const { unmount } = renderJourney();
      fireEvent.click(
        await screen.findByRole("button", { name: en.Purchase.manage })
      );
      await waitFor(() =>
        expect(
          fetchMock.mock.calls.some(([url]) =>
            String(url).endsWith("/widget-bootstrap")
          )
        ).toBe(true)
      );
      if (event === "unmount") unmount();
      else
        act(() => {
          window.localStorage.removeItem(sessionStorageKey);
          window.dispatchEvent(
            event === "same-tab"
              ? new Event(sessionChangedEvent)
              : new StorageEvent("storage", {
                  key: sessionStorageKey,
                  storageArea: window.localStorage
                })
          );
        });
      await act(async () =>
        resolve(
          json({
            mode: "SIMULATED",
            credential: "SIMULATED:" + "x".repeat(32),
            sdk: "isolated_stub",
            widget_origin: "self",
            disableCreateSubscription: true,
            disableEditSubscription: true
          })
        )
      );
      expect(screen.queryByText(en.Purchase.stub)).not.toBeInTheDocument();
      expect(JSON.stringify(Object.entries(window.localStorage))).not.toContain(
        "SIMULATED:"
      );
      expect(
        JSON.stringify(Object.entries(window.sessionStorage))
      ).not.toContain("SIMULATED:");
    }
  );
});
