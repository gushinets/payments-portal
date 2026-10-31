import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ProductBilling } from "@/features/billing";
import type { PurchaseIntentResponse } from "@/generated/api-contracts/types.gen";
import ru from "@/messages/ru.json";
import { sessionStorageKey } from "@/shared/api/auth";
import { purchaseReview, purchaseUser, savedPurchase, widgetResponse } from "../fixtures/purchase";
import { renderWithIntl } from "../setup/render-with-intl";

const { mount, dispose } = vi.hoisted(() => ({ mount: vi.fn(), dispose: vi.fn() }));
// Test-only SDK substitution; all Portal endpoint adapters/transport remain real.
vi.mock("@/features/billing/official-widget-sdk", () => ({ mountOfficialWidget: mount }));
const messages = { Purchase: ru.Purchase, Billing: ru.Billing, CatalogPreview: ru.CatalogPreview };
const fetcher = vi.fn<typeof fetch>();
let owned: PurchaseIntentResponse | null;
const review = vi.fn();
const confirm = vi.fn();
const advance = vi.fn();
const bootstrap = vi.fn();
const json = (payload: unknown, status = 200) => Response.json(payload, { status });

function renderProduct(user = purchaseUser) {
  return renderWithIntl(<ProductBilling productId="proposal_ai" user={user} />, { locale: "ru", messages });
}
async function accept() {
  fireEvent.click(await screen.findByRole("button", { name: ru.Purchase.buy }));
  fireEvent.click(await screen.findByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: ru.Purchase.confirm }));
}

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
  window.localStorage.setItem(sessionStorageKey, "synthetic-portal-session");
  owned = null;
  review.mockReset().mockImplementation(async () => json(purchaseReview));
  confirm.mockReset().mockImplementation(async () => {
    owned = { ...savedPurchase, state: "created" };
    return json(owned);
  });
  advance.mockReset().mockImplementation(async () => { owned = savedPurchase; return json(owned); });
  bootstrap.mockReset().mockImplementation(async (init: RequestInit) => json(widgetResponse(String(init.body).includes("purchase_intent_id"))));
  mount.mockReset().mockReturnValue(dispose);
  dispose.mockReset();
  fetcher.mockReset().mockImplementation(async (input, init) => {
    const path = new URL(String(input)).pathname;
    if (path === "/api/auth/session") return json({ authenticated: true, user: purchaseUser });
    if (path === "/api/purchase-intents/current") return json({ purchase: owned });
    if (path === "/api/purchases/review") return review(init);
    if (path === "/api/purchase-intents") return confirm(init);
    if (path.endsWith("/advance")) return advance(init);
    if (path === "/api/billing/widget-bootstrap") return bootstrap(init);
    if (path === `/api/purchase-intents/${savedPurchase.purchase_intent_id}`) return json(owned);
    throw new Error("unexpected_synthetic_request");
  });
  vi.stubGlobal("fetch", fetcher);
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("ANY-709 Step 4 purchase journey", () => {
  it("keeps guests read-only and verifies email before personal requests", async () => {
    window.localStorage.clear();
    const guest = renderWithIntl(<ProductBilling productId="proposal_ai" />, { locale: "ru", messages });
    expect(await screen.findByRole("link", { name: ru.Purchase.signIn })).toHaveAttribute("href", "/ru/account");
    expect(fetcher).not.toHaveBeenCalled();
    guest.unmount();
    renderProduct({ ...purchaseUser, email_verified: false });
    expect(screen.getByText(ru.Purchase.verification)).toBeVisible();
    expect(screen.queryByRole("button", { name: ru.Purchase.buy })).not.toBeInTheDocument();
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("reviews exact terms/consent then confirms once and links to cabinet without opening billing", async () => {
    renderProduct();
    expect(await screen.findByRole("button", { name: ru.Purchase.buy })).toBeVisible();
    expect(review).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: ru.Purchase.buy }));
    const checkbox = await screen.findByRole("checkbox");
    expect(screen.getByText(ru.Purchase.draftLegal)).toBeVisible();
    expect(screen.getByRole("link", { name: /Тестовый проект/ })).toHaveAttribute("lang", "ru");
    expect(screen.getByRole("button", { name: ru.Purchase.confirm })).toBeDisabled();
    fireEvent.click(checkbox);
    const button = screen.getByRole("button", { name: ru.Purchase.confirm });
    fireEvent.click(button); fireEvent.click(button);
    expect(await screen.findByRole("link", { name: ru.Purchase.manage })).toHaveAttribute("href", `/ru/account?purchase=${savedPurchase.purchase_intent_id}#billing`);
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(advance).toHaveBeenCalledTimes(1);
    expect(JSON.parse(String(confirm.mock.calls[0][0].body))).toEqual({
      product_id: "proposal_ai", revision_id: purchaseReview.revision_id, expected_fingerprint: purchaseReview.expected_fingerprint,
      documents: purchaseReview.documents.map(({ document_version_id, acceptance_text_hash }) => ({ document_version_id, acceptance_text_hash }))
    });
    expect(confirm.mock.calls[0][0].headers["Idempotency-Key"]).toBeTruthy();
    expect(bootstrap).not.toHaveBeenCalled();
    expect(mount).not.toHaveBeenCalled();
    expect(screen.getByRole("heading", { name: ru.Purchase.states.linked })).toBeVisible();
    expect(screen.getByText(ru.Purchase.managedInAccount)).toBeVisible();
    expect(document.body).not.toHaveTextContent("synthetic-widget-token");
    expect(Object.keys(window.localStorage)).toEqual([sessionStorageKey]);
    expect(window.sessionStorage.length).toBe(0);
    expect(window.location.href).not.toContain("synthetic-widget-token");
  });

  it("keeps the same key and accepted meaning after a lost confirmation response", async () => {
    confirm.mockRejectedValueOnce(new TypeError("private-network-detail"));
    renderProduct();
    await accept();
    expect(await screen.findByRole("alert")).not.toHaveTextContent("private-network-detail");
    fireEvent.click(screen.getByRole("button", { name: ru.Purchase.refresh }));
    await waitFor(() => expect(screen.getByRole("button", { name: ru.Purchase.retryConfirm })).toBeEnabled());
    expect(screen.getByRole("checkbox")).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: ru.Purchase.retryConfirm }));
    expect(await screen.findByRole("link", { name: ru.Purchase.manage })).toHaveAttribute("href", `/ru/account?purchase=${savedPurchase.purchase_intent_id}#billing`);
    expect(confirm).toHaveBeenCalledTimes(2);
    expect(confirm.mock.calls[0][0].headers["Idempotency-Key"]).toBe(confirm.mock.calls[1][0].headers["Idempotency-Key"]);
    expect(confirm.mock.calls[0][0].body).toBe(confirm.mock.calls[1][0].body);
    expect(review).toHaveBeenCalledTimes(1);
  });

  it("retains frozen consent and the same key for an explicit retry after billing contention", async () => {
    confirm.mockResolvedValueOnce(json({ detail: { code: "billing_busy", request_id: "synthetic-contention" } }, 503));
    renderProduct();
    await accept();
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(ru.Billing.errors.unavailable);
    expect(alert).toHaveTextContent("synthetic-contention");
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(advance).not.toHaveBeenCalled();
    expect(screen.getByRole("checkbox")).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: ru.Purchase.retryConfirm }));
    expect(await screen.findByRole("link", { name: ru.Purchase.manage })).toBeVisible();
    expect(confirm).toHaveBeenCalledTimes(2);
    expect(confirm.mock.calls[1][0].headers["Idempotency-Key"]).toBe(confirm.mock.calls[0][0].headers["Idempotency-Key"]);
    expect(confirm.mock.calls[1][0].body).toBe(confirm.mock.calls[0][0].body);
    expect(review).toHaveBeenCalledTimes(1);
    expect(advance).toHaveBeenCalledTimes(1);
  });

  it("discovers a confirmed intent after a lost response without another confirm or advance", async () => {
    confirm.mockImplementationOnce(async () => {
      owned = { ...savedPurchase, state: "created" };
      throw new DOMException("synthetic_timeout", "AbortError");
    });
    renderProduct();
    await accept();
    fireEvent.click(await screen.findByRole("button", { name: ru.Purchase.continue }));
    expect(await screen.findByRole("link", { name: ru.Purchase.manage })).toHaveAttribute("href", `/ru/account?purchase=${savedPurchase.purchase_intent_id}#billing`);
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(advance).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: ru.Purchase.buy })).not.toBeInTheDocument();
  });

  it("recovers a successful preparation after a browser timeout using only local status", async () => {
    advance.mockImplementationOnce(async () => {
      owned = savedPurchase;
      throw new DOMException("synthetic_timeout", "AbortError");
    });
    renderProduct();
    await accept();
    expect(await screen.findByRole("link", { name: ru.Purchase.manage })).toBeVisible();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: ru.Purchase.buy })).not.toBeInTheDocument();
    expect(advance).toHaveBeenCalledTimes(1);
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(bootstrap).not.toHaveBeenCalled(); // A local GET is not payment proof.
    expect(fetcher.mock.calls.some(([url]) => String(url).endsWith(`/${savedPurchase.purchase_intent_id}`))).toBe(true);

  });

  it("keeps the held intent and shows recovery when timeout status inspection also fails", async () => {
    advance.mockImplementationOnce(async () => {
      fetcher.mockRejectedValueOnce(new TypeError("synthetic_status_unavailable"));
      throw new DOMException("synthetic_timeout", "AbortError");
    });
    renderProduct();
    await accept();
    expect(await screen.findByRole("alert")).toHaveTextContent(ru.Billing.errors.financialPending);
    expect(screen.getByRole("button", { name: ru.Purchase.continue })).toBeEnabled();
    expect(screen.queryByRole("button", { name: ru.Purchase.buy })).not.toBeInTheDocument();
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(advance).toHaveBeenCalledTimes(1);
  });

  it("requires fresh review and unchecked consents after terms_changed", async () => {
    confirm.mockResolvedValueOnce(json({ detail: { code: "terms_changed", request_id: "changed-123" } }, 409));
    renderProduct();
    await accept();
    expect(await screen.findByRole("alert")).toHaveTextContent(ru.Billing.errors.termsChanged);
    expect(advance).not.toHaveBeenCalled();
    const fresh = { ...purchaseReview, terms: { ...purchaseReview.terms, recurring_amount: "150" }, expected_fingerprint: "sha256:" + "d".repeat(64) };
    review.mockResolvedValueOnce(json(fresh));
    fireEvent.click(screen.getByRole("button", { name: ru.Purchase.buy }));
    expect(await screen.findByRole("checkbox")).not.toBeChecked();
    expect(screen.getByText("150 RUB", { exact: false })).toBeVisible();
    expect(confirm).toHaveBeenCalledTimes(1);
  });

  it.each(["created", "preparing", "awaiting_external_result", "manual_review"] as const)("reload resumes the same held %s purchase without a new review", async (state) => {
    owned = { ...savedPurchase, state, reason: state === "manual_review" ? "purchase_outcome_unknown" : "purchase_pending" };
    advance.mockImplementation(async () => json(owned));
    renderProduct();
    const action = await screen.findByRole("button", { name: state === "created" ? ru.Purchase.continue : ru.Purchase.recover });
    expect(screen.queryByRole("button", { name: ru.Purchase.buy })).not.toBeInTheDocument();
    fireEvent.click(action);
    await waitFor(() => expect(advance).toHaveBeenCalledTimes(1));
    expect(fetcher.mock.calls.some(([url]) => String(url).endsWith(`/${savedPurchase.purchase_intent_id}/advance`))).toBe(true);
    expect(review).not.toHaveBeenCalled(); expect(confirm).not.toHaveBeenCalled();
    expect(bootstrap).not.toHaveBeenCalled();
  });

  it("restores the compact prepared state without current catalog or billing reads", async () => {
    owned = savedPurchase;
    renderProduct();
    expect(await screen.findByRole("link", { name: ru.Purchase.manage })).toHaveAttribute("href", `/ru/account?purchase=${savedPurchase.purchase_intent_id}#billing`);
    expect(screen.queryByRole("button", { name: ru.Purchase.buy })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: ru.Billing.open })).not.toBeInTheDocument();
    expect(review).not.toHaveBeenCalled(); expect(advance).not.toHaveBeenCalled();
    expect(bootstrap).not.toHaveBeenCalled();
    expect(fetcher.mock.calls.some(([url]) => String(url).includes("catalog"))).toBe(false);
  });

  it("keeps unknown status distinct from no purchase and retries without Buy", async () => {
    fetcher.mockRejectedValueOnce(new TypeError("offline"));
    renderProduct();
    expect(await screen.findByText(ru.Purchase.unknown)).toBeVisible();
    expect(screen.queryByRole("button", { name: ru.Purchase.buy })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: ru.Purchase.refresh }));
    expect(await screen.findByRole("button", { name: ru.Purchase.buy })).toBeVisible();
  });

  it.each([["lbx_provider_rejected", "rejected"], ["lbx_unavailable", "unavailable"], ["lbx_authentication_failed", "serverAuth"], ["lbx_response_invalid", "response"], ["purchase_pending", "financialPending"]] as const)("uses normalized %s diagnostics without provider text", async (code, key) => {
    review.mockResolvedValueOnce(json({ detail: { code, request_id: "support-123", error: "secret-provider-text" } }, 503));
    renderProduct();
    fireEvent.click(await screen.findByRole("button", { name: ru.Purchase.buy }));
    expect(await screen.findByRole("alert")).toHaveTextContent("support-123");
    expect(screen.getByRole("alert")).toHaveTextContent(ru.Billing.errors[key]);
    expect(document.body).not.toHaveTextContent("secret-provider-text");
  });


});

it("official SDK accepts the server payment presentation and keeps all unsupported actions disabled", async () => {
  const actual = await vi.importActual<typeof import("@/features/billing/official-widget-sdk")>("@/features/billing/official-widget-sdk");
  const port = () => ({ close: vi.fn(), postMessage: vi.fn(), onmessage: null });
  vi.stubGlobal("MessageChannel", class { port1 = port(); port2 = port(); });
  const node = document.createElement("div");
  const response = widgetResponse(true);
  const destroy = actual.mountOfficialWidget(node, response, "Synthetic billing", () => true, vi.fn());
  expect(node.querySelector("iframe")).not.toBeNull();
  expect(node.querySelector("iframe")).toHaveAttribute("sandbox", expect.stringContaining("allow-forms allow-popups"));
  expect(response.credential).toBe("");
  expect(node.innerHTML).not.toContain("synthetic-widget-token");
  destroy();
  expect(node.childElementCount).toBe(0);
  expect(() => actual.mountOfficialWidget(node, { ...widgetResponse(true), disablePayments: true }, "Synthetic billing", () => true, vi.fn())).toThrow("widget_configuration_refused");
});
