import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ProductBilling } from "@/features/billing";
import { ProductDetailContent } from "@/features/catalog/ProductDetailContent";
import type { PurchaseIntentResponse } from "@/generated/api-contracts/types.gen";
import ru from "@/messages/ru.json";
import { sessionStorageKey } from "@/shared/api/auth";
import { purchaseReview, purchaseUser, savedPurchase, widgetResponse } from "../fixtures/purchase";
import { simulatedProduct } from "../fixtures/catalog";
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
const catalog = vi.fn();
const json = (payload: unknown, status = 200) => Response.json(payload, { status });

function renderProduct(user = purchaseUser) {
  return renderWithIntl(<ProductBilling productId="proposal_ai" offerAvailable user={user} />, { locale: "ru", messages });
}

it("keeps incomplete inventory retryable without a support conflict or another confirmation", async () => {
  advance.mockImplementationOnce(async () => {
    owned = { ...savedPurchase, state: "awaiting_external_result" };
    return json({ detail: { code: "purchase_inventory_incomplete", request_id: "inventory-pending" } }, 409);
  });
  renderProduct();
  await accept();
  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent(ru.Billing.errors.financialPending);
  expect(alert).toHaveTextContent("inventory-pending");
  expect(alert).not.toHaveTextContent(ru.Billing.errors.purchaseConflict);
  fireEvent.click(await screen.findByRole("button", { name: ru.Purchase.continue }));
  expect(await screen.findByRole("link", { name: ru.Billing.pay })).toBeVisible();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(confirm).toHaveBeenCalledTimes(1);
  expect(advance).toHaveBeenCalledTimes(2);
});

it("recovers a concurrent confirmation without a false support warning or another advance", async () => {
  confirm.mockImplementationOnce(async () => {
    owned = { ...savedPurchase, state: "created" };
    return json({ detail: { code: "purchase_scope_occupied", request_id: "original-conflict" } }, 409);
  });
  renderProduct();
  await accept();
  expect(await screen.findByRole("button", { name: ru.Purchase.continue })).toBeVisible();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(advance).not.toHaveBeenCalled();
});

it("preserves the original conflict when the recovery lookup fails", async () => {
  let lookupFails = false;
  const ordinaryFetch = fetcher.getMockImplementation()!;
  fetcher.mockImplementation(async (input, init) => {
    if (lookupFails && new URL(String(input)).pathname === "/api/purchase-intents/current") {
      return json({ detail: { code: "billing_session_required", request_id: "lookup-failure" } }, 401);
    }
    return ordinaryFetch(input, init);
  });
  confirm.mockImplementationOnce(async () => {
    lookupFails = true;
    return json({ detail: { code: "purchase_scope_occupied", request_id: "original-conflict" } }, 409);
  });
  renderProduct();
  await accept();
  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent(ru.Billing.errors.purchaseConflict);
  expect(alert).toHaveTextContent("original-conflict");
  expect(alert).not.toHaveTextContent("lookup-failure");
  expect(advance).not.toHaveBeenCalled();
});

it("reports invalid currency configuration without blaming the offer source", async () => {
  review.mockResolvedValueOnce(json({ detail: { code: "lbx_currency_invalid", request_id: "currency-config" } }, 503));
  renderProduct();
  fireEvent.click(await screen.findByRole("button", { name: ru.Purchase.buy }));
  expect(await screen.findByRole("alert")).toHaveTextContent(ru.Billing.errors.configuration);
  expect(confirm).not.toHaveBeenCalled();
});

it.each(["UNMAPPED", "OFFER_INCOMPLETE", "OFFER_UNSUPPORTED"] as const)(
  "disables new Buy for %s using the same offer read as its preview", async (availability) => {
    catalog.mockResolvedValueOnce(json({ ...simulatedProduct, availability, offer: null }));
    renderWithIntl(<ProductDetailContent productId="proposal_ai">{null}</ProductDetailContent>, { locale: "ru", messages });
    expect(await screen.findByRole("button", { name: ru.Purchase.buy })).toBeDisabled();
    await waitFor(() => expect(catalog).toHaveBeenCalledTimes(1));
    expect(review).not.toHaveBeenCalled();
  }
);

it("enables new Buy after the current offer loads", async () => {
  let resolve!: (response: Response) => void;
  catalog.mockImplementationOnce(() => new Promise<Response>((done) => { resolve = done; }));
  renderWithIntl(<ProductDetailContent productId="proposal_ai">{null}</ProductDetailContent>, { locale: "ru", messages });
  expect(await screen.findByRole("button", { name: ru.Purchase.buy })).toBeDisabled();
  resolve(json(simulatedProduct));
  await waitFor(() => expect(screen.getByRole("button", { name: ru.Purchase.buy })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: ru.Purchase.buy }));
  expect(await screen.findByRole("checkbox")).toBeVisible();
});

it.each(["created", "linked"] as const)("keeps existing %s purchase usable when the catalog is down", async (state) => {
  owned = { ...savedPurchase, state };
  catalog.mockResolvedValueOnce(json({ detail: { code: "catalog_unavailable" } }, 503));
  renderWithIntl(<ProductDetailContent productId="proposal_ai">{null}</ProductDetailContent>, { locale: "ru", messages });
  const action = state === "linked"
    ? await screen.findByRole("link", { name: ru.Billing.pay })
    : await screen.findByRole("button", { name: ru.Purchase.continue });
  expect(action).toBeVisible();
  expect(action).not.toBeDisabled();
});
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
  catalog.mockReset().mockImplementation(async () => json(simulatedProduct));
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
    if (path === "/api/catalog/products/proposal_ai") return catalog();
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
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); });

it("shows Continue when status polling learns the agreement has been recovered", async () => {
  owned = { ...savedPurchase, state: "awaiting_external_result", reason: "purchase_pending" };
  renderProduct();
  expect(await screen.findByRole("button", { name: ru.Purchase.recover })).toBeEnabled();

  owned = { ...owned, state: "preparing" };

  expect(await screen.findByRole("button", { name: ru.Purchase.continue }, { timeout: 4000 })).toBeEnabled();
  expect(screen.queryByText(ru.Purchase.states.awaiting_external_result)).not.toBeInTheDocument();
  expect(advance).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: ru.Purchase.continue }));
  expect(await screen.findByRole("link", { name: ru.Billing.pay })).toBeVisible();
  expect(advance).toHaveBeenCalledTimes(1);
});

it.each([ru.Purchase.recover, ru.Purchase.refresh])("announces recovery and moves focus from %s to payment", async (action) => {
  vi.useFakeTimers();
  owned = { ...savedPurchase, state: "awaiting_external_result" };
  await act(async () => { renderProduct(); });
  const status = screen.getByText(ru.Purchase.states.awaiting_external_result).closest('[role="status"]');
  expect(status).toBeInTheDocument();
  screen.getByRole("button", { name: action }).focus();

  owned = savedPurchase;
  await act(async () => vi.advanceTimersByTimeAsync(2100));

  expect(status).toHaveTextContent(ru.Purchase.states.linked);
  expect(screen.getByRole("link", { name: ru.Billing.pay })).toHaveFocus();
});

it("keeps accepted terms open and focused when polling makes payment available", async () => {
  vi.useFakeTimers();
  owned = { ...savedPurchase, state: "awaiting_external_result" };
  await act(async () => { renderProduct(); });
  const summary = screen.getByText(ru.Purchase.acceptedTerms);
  const details = summary.closest("details")!;
  details.open = true;
  summary.focus();

  owned = savedPurchase;
  await act(async () => vi.advanceTimersByTimeAsync(2100));

  expect(screen.getByRole("link", { name: ru.Billing.pay })).toBeVisible();
  expect(screen.getByText(ru.Purchase.acceptedTerms)).toBe(summary);
  expect(summary).toHaveFocus();
  expect(details).toHaveAttribute("open");
});

it.each([ru.Purchase.recover, ru.Purchase.refresh])("moves focus from %s when its response makes payment available", async (action) => {
  owned = { ...savedPurchase, state: "awaiting_external_result" };
  renderProduct();
  const trigger = await screen.findByRole("button", { name: action });
  trigger.focus();

  owned = savedPurchase;
  fireEvent.click(trigger);

  expect(await screen.findByRole("link", { name: ru.Billing.pay })).toHaveFocus();
});

it("offers payment from saved status before advance replies and ignores the older reply", async () => {
  vi.useFakeTimers();
  const reply = Promise.withResolvers<Response>();
  advance.mockReturnValueOnce(reply.promise);
  await act(async () => { renderProduct(); });
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: ru.Purchase.buy })); });
  fireEvent.click(screen.getByRole("checkbox"));
  const confirmButton = screen.getByRole("button", { name: ru.Purchase.confirm });
  confirmButton.focus();
  await act(async () => { fireEvent.click(confirmButton); });
  expect(advance).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("button", { name: ru.Purchase.continue })).toHaveFocus();
  expect(screen.queryByRole("link", { name: ru.Billing.pay })).not.toBeInTheDocument();

  owned = savedPurchase;
  await act(async () => vi.advanceTimersByTimeAsync(10_000));

  expect(screen.getByRole("link", { name: ru.Billing.pay })).toHaveFocus();
  await act(async () => reply.resolve(json({ ...savedPurchase, state: "awaiting_external_result" })));
  expect(screen.getByRole("link", { name: ru.Billing.pay })).toBeVisible();
  expect(confirm).toHaveBeenCalledTimes(1);
  expect(advance).toHaveBeenCalledTimes(1);
});

it.each(["polling", "advance recovery", "manual check"] as const)("keeps polling after a mixed release status from %s", async (source) => {
  vi.useFakeTimers();
  const original = { ...savedPurchase, state: "created" } satisfies PurchaseIntentResponse;
  const statusPath = `/api/purchase-intents/${original.purchase_intent_id}`;
  const statusReadCount = () => fetcher.mock.calls.filter(([url]) => new URL(String(url)).pathname === statusPath).length;
  owned = original;
  await act(async () => { renderProduct(); });
  const continueButton = screen.getByRole("button", { name: ru.Purchase.continue });
  continueButton.focus();

  // The status read saw the old purchase state and the already removed hold.
  owned = { ...original, scope_held: false };
  if (source === "advance recovery") {
    advance.mockResolvedValueOnce(json({ detail: { request_id: "gateway-timeout" } }, 504));
    await act(async () => { fireEvent.click(continueButton); });
  } else if (source === "manual check") {
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: ru.Purchase.refresh })); });
  } else {
    await act(async () => vi.advanceTimersByTimeAsync(2_000));
  }
  expect(statusReadCount()).toBe(1);
  expect(screen.queryByRole("button", { name: ru.Purchase.buy })).not.toBeInTheDocument();
  if (source === "advance recovery") expect(screen.getByRole("alert")).toHaveTextContent("gateway-timeout");

  owned = { ...original, state: "failed_before_external_effect", scope_held: false, reason: "terms_changed" };
  await act(async () => vi.advanceTimersByTimeAsync(5_000));

  expect(statusReadCount()).toBe(2);
  expect(screen.getByText(ru.Purchase.termsChanged)).toBeVisible();
  expect(screen.getByRole("button", { name: ru.Purchase.buy })).toHaveFocus();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  await act(async () => vi.advanceTimersByTimeAsync(10_000));
  expect(statusReadCount()).toBe(2);
  expect(advance).toHaveBeenCalledTimes(source === "advance recovery" ? 1 : 0);
});

it("offers a new terms review when polling confirms release before advance replies", async () => {
  vi.useFakeTimers();
  const reply = Promise.withResolvers<Response>();
  const original = { ...savedPurchase, state: "created" } satisfies PurchaseIntentResponse;
  owned = original;
  advance.mockReturnValueOnce(reply.promise);
  await act(async () => { renderProduct(); });
  const continueButton = screen.getByRole("button", { name: ru.Purchase.continue });
  continueButton.focus();
  await act(async () => { fireEvent.click(continueButton); });
  expect(advance).toHaveBeenCalledTimes(1);

  owned = { ...original, state: "failed_before_external_effect", scope_held: false, reason: "terms_changed" };
  await act(async () => vi.advanceTimersByTimeAsync(5_000));

  expect(screen.getByText(ru.Purchase.termsChanged)).toBeVisible();
  expect(screen.queryByText(ru.Purchase.working)).not.toBeInTheDocument();
  expect(review).not.toHaveBeenCalled();
  const buyButton = screen.getByRole("button", { name: ru.Purchase.buy });
  expect(buyButton).toHaveFocus();
  owned = null;
  await act(async () => { fireEvent.click(buyButton); });
  expect(screen.getByRole("checkbox")).not.toBeChecked();

  await act(async () => reply.resolve(json(original)));
  expect(screen.getByRole("checkbox")).not.toBeChecked();
  expect(review).toHaveBeenCalledTimes(1);
  expect(confirm).not.toHaveBeenCalled();
  expect(advance).toHaveBeenCalledTimes(1);
});

it("moves focus to the status check when polling confirms release without an available offer", async () => {
  vi.useFakeTimers();
  const reply = Promise.withResolvers<Response>();
  const original = { ...savedPurchase, state: "created" } satisfies PurchaseIntentResponse;
  owned = original;
  advance.mockReturnValueOnce(reply.promise);
  await act(async () => {
    renderWithIntl(<ProductBilling productId="proposal_ai" offerAvailable={false} user={purchaseUser} />, { locale: "ru", messages });
  });
  const continueButton = screen.getByRole("button", { name: ru.Purchase.continue });
  continueButton.focus();
  await act(async () => { fireEvent.click(continueButton); });

  owned = { ...original, state: "failed_before_external_effect", scope_held: false, reason: "terms_changed" };
  await act(async () => vi.advanceTimersByTimeAsync(5_000));

  const refreshButton = screen.getByRole("button", { name: ru.Purchase.refresh });
  expect(refreshButton).toBeEnabled();
  expect(refreshButton).toHaveFocus();
  await act(async () => reply.resolve(json(original)));
});

it("observes a subscription recovered after the fast polling window using status reads only", async () => {
  vi.useFakeTimers();
  owned = { ...savedPurchase, state: "awaiting_external_result", reason: "purchase_pending" };
  await act(async () => { renderProduct(); });
  expect(screen.getByRole("button", { name: ru.Purchase.recover })).toBeEnabled();

  await act(async () => { await vi.advanceTimersByTimeAsync(155_000); });
  owned = savedPurchase;
  await act(async () => { await vi.advanceTimersByTimeAsync(65_000); });

  expect(screen.getByRole("link", { name: ru.Billing.pay })).toBeVisible();
  expect(advance).not.toHaveBeenCalled();
  expect(confirm).not.toHaveBeenCalled();
});

it("announces that polling has stopped and keeps the manual status check available", async () => {
  vi.useFakeTimers();
  owned = { ...savedPurchase, state: "awaiting_external_result", reason: "purchase_pending" };
  await act(async () => { renderProduct(); });
  await act(async () => { await vi.advanceTimersByTimeAsync(123 * 60_000); });
  expect(screen.getByText(ru.Purchase.statusPollingPaused)).toBeVisible();

  fetcher.mockClear();
  owned = savedPurchase;
  await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
  expect(fetcher).not.toHaveBeenCalled();
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: ru.Purchase.refresh })); });
  expect(screen.getByRole("link", { name: ru.Billing.pay })).toBeVisible();
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(advance).not.toHaveBeenCalled();
});

describe("ANY-709 Step 4 purchase journey", () => {
  it("keeps guests read-only and verifies email before personal requests", async () => {
    window.localStorage.clear();
    const guest = renderWithIntl(<ProductBilling productId="proposal_ai" offerAvailable />, { locale: "ru", messages });
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
    expect(screen.getByText("100 generation")).toBeVisible();
    expect(screen.getByText(ru.Purchase.simulatedTerms)).toBeVisible();
    expect(screen.getByText("proposal_ai.test_generations")).toBeVisible();
    expect(screen.getByRole("link", { name: /Тестовый проект/ })).toHaveAttribute("lang", "ru");
    expect(screen.getByRole("button", { name: ru.Purchase.confirm })).toBeDisabled();
    fireEvent.click(checkbox);
    const button = screen.getByRole("button", { name: ru.Purchase.confirm });
    fireEvent.click(button); fireEvent.click(button);
    expect(await screen.findByRole("link", { name: ru.Billing.pay })).toHaveAttribute("href", `/ru/account?purchase=${savedPurchase.purchase_intent_id}#billing`);
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(advance).toHaveBeenCalledTimes(1);
    expect(JSON.parse(String(confirm.mock.calls[0][0].body))).toEqual({
      product_id: "proposal_ai", revision_id: purchaseReview.revision_id, expected_fingerprint: purchaseReview.expected_fingerprint,
      expected_technical_terms_digest: purchaseReview.expected_technical_terms_digest,
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
    expect(await screen.findByRole("link", { name: ru.Billing.pay })).toHaveAttribute("href", `/ru/account?purchase=${savedPurchase.purchase_intent_id}#billing`);
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
    expect(await screen.findByRole("link", { name: ru.Billing.pay })).toBeVisible();
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
    expect(await screen.findByRole("link", { name: ru.Billing.pay })).toHaveAttribute("href", `/ru/account?purchase=${savedPurchase.purchase_intent_id}#billing`);
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(advance).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: ru.Purchase.buy })).not.toBeInTheDocument();
  });

  it.each([
    { state: "created", role: "button", name: ru.Purchase.continue, focus: "retry" },
    { state: "awaiting_external_result", role: "button", name: ru.Purchase.recover, focus: "retry" },
    { state: "linked", role: "link", name: ru.Billing.pay, focus: "retry" },
    { state: "created", role: "button", name: ru.Purchase.continue, focus: "status check" },
  ] as const)("finds a late committed confirmation in $state with focus on $focus", async ({ state, role, name, focus }) => {
    vi.useFakeTimers();
    confirm.mockRejectedValueOnce(new TypeError("synthetic_lost_reply"));
    await act(async () => { renderProduct(); });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: ru.Purchase.buy })); });
    fireEvent.click(screen.getByRole("checkbox"));
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: ru.Purchase.confirm })); });
    expect(screen.getByRole("alert")).toHaveTextContent(ru.Billing.errors.financialPending);
    const retry = screen.getByRole("button", { name: ru.Purchase.retryConfirm });
    const statusCheck = screen.getByRole("button", { name: ru.Purchase.refresh });
    const previous = focus === "retry" ? retry : statusCheck;
    previous.focus();
    expect(previous).toHaveFocus();

    owned = { ...savedPurchase, state };
    await act(async () => vi.advanceTimersByTimeAsync(2_100));

    const action = screen.getByRole(role, { name });
    expect(action).toBeEnabled();
    expect(retry).not.toBeInTheDocument();
    expect(focus === "retry" ? action : statusCheck).toHaveFocus();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(advance).not.toHaveBeenCalled();
    expect(bootstrap).not.toHaveBeenCalled();
  });

  it("recovers a successful preparation after a browser timeout using only local status", async () => {
    advance.mockImplementationOnce(async () => {
      owned = savedPurchase;
      throw new DOMException("synthetic_timeout", "AbortError");
    });
    renderProduct();
    await accept();
    expect(await screen.findByRole("link", { name: ru.Billing.pay })).toBeVisible();
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
    const fresh = { ...purchaseReview, expected_technical_terms_digest: "sha256:" + "f".repeat(64), technical_terms: { ...purchaseReview.technical_terms!, offer: { ...purchaseReview.technical_terms!.offer, quantity: 101 } }, terms: { ...purchaseReview.terms, recurring_amount: "150" }, expected_fingerprint: "sha256:" + "d".repeat(64) };
    review.mockResolvedValueOnce(json(fresh));
    fireEvent.click(screen.getByRole("button", { name: ru.Purchase.buy }));
    expect(await screen.findByRole("checkbox")).not.toBeChecked();
    expect(screen.getByText("150 RUB", { exact: false })).toBeVisible();
    expect(screen.getByText("101 generation")).toBeVisible();
    expect(confirm).toHaveBeenCalledTimes(1);
  });

  it.each(["created", "preparing", "awaiting_external_result", "manual_review"] as const)("reload resumes the same held %s purchase without a new review", async (state) => {
    owned = { ...savedPurchase, state, reason: state === "manual_review" ? "purchase_outcome_unknown" : "purchase_pending" };
    advance.mockImplementation(async () => json(owned));
    renderProduct();
    const action = await screen.findByRole("button", { name: state === "created" || state === "preparing" ? ru.Purchase.continue : ru.Purchase.recover });
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
    expect(await screen.findByRole("link", { name: ru.Billing.pay })).toHaveAttribute("href", `/ru/account?purchase=${savedPurchase.purchase_intent_id}#billing`);
    expect(screen.queryByRole("button", { name: ru.Purchase.buy })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: ru.Billing.open })).not.toBeInTheDocument();
    expect(review).not.toHaveBeenCalled(); expect(advance).not.toHaveBeenCalled();
    expect(bootstrap).not.toHaveBeenCalled();
    expect(fetcher.mock.calls.some(([url]) => String(url).includes("catalog"))).toBe(false);
  });

  it("keeps legacy missing technical history unavailable without current fixture values", async () => {
    owned = { ...savedPurchase, accepted: { ...purchaseReview, technical_terms: null, expected_technical_terms_digest: null } };
    renderProduct();
    fireEvent.click(await screen.findByText(ru.Purchase.acceptedTerms));
    expect(screen.getByText(ru.Purchase.technicalUnknown)).toBeVisible();
    expect(screen.queryByText("100 generation")).not.toBeInTheDocument();
    expect(screen.queryByText(ru.Purchase.simulatedTerms)).not.toBeInTheDocument();
    expect(review).not.toHaveBeenCalled();
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
  const destroy = actual.mountOfficialWidget(node, response, "Synthetic billing", () => true, vi.fn(), vi.fn());
  expect(node.querySelector("iframe")).not.toBeNull();
  expect(node.querySelector("iframe")).toHaveAttribute("sandbox", expect.stringContaining("allow-forms allow-popups"));
  expect(response.credential).toBe("");
  expect(node.innerHTML).not.toContain("synthetic-widget-token");
  destroy();
  expect(node.childElementCount).toBe(0);
});

it("continues checking a lost confirmation after an empty manual status check", async () => {
  confirm.mockRejectedValueOnce(new TypeError("synthetic_lost_reply"));
  renderProduct();
  await accept();
  expect(await screen.findByRole("alert")).toHaveTextContent(ru.Billing.errors.financialPending);

  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: ru.Purchase.refresh }));
  });
  expect(screen.getByRole("button", { name: ru.Purchase.retryConfirm })).toBeEnabled();

  owned = { ...savedPurchase, state: "created" };
  expect(await screen.findByRole("button", { name: ru.Purchase.continue }, { timeout: 3000 })).toBeEnabled();
  expect(confirm).toHaveBeenCalledTimes(1);
  expect(advance).not.toHaveBeenCalled();
});

it("keeps the unknown-outcome warning through preparation and clears it once the purchase is linked", async () => {
  advance.mockImplementationOnce(async () => {
    owned = { ...savedPurchase, state: "awaiting_external_result", reason: "purchase_pending" };
    throw new TypeError("synthetic_lost_advance_reply");
  });
  renderProduct();
  await accept();
  expect(await screen.findByRole("alert")).toHaveTextContent(ru.Billing.errors.financialPending);
  expect(screen.getByRole("button", { name: ru.Purchase.recover })).toBeEnabled();

  owned = { ...savedPurchase, state: "preparing", reason: "purchase_pending" };
  expect(await screen.findByRole("button", { name: ru.Purchase.continue }, { timeout: 3000 })).toBeEnabled();
  expect(screen.getByRole("alert")).toHaveTextContent(ru.Billing.errors.financialPending);
  expect(advance).toHaveBeenCalledTimes(1);

  owned = savedPurchase;
  expect(await screen.findByRole("link", { name: ru.Billing.pay }, { timeout: 3000 })).toBeVisible();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(advance).toHaveBeenCalledTimes(1);
});

it.each(["immediate status", "subsequent poll"] as const)("keeps an unknown-outcome warning when preparing first arrives via %s", async (firstRead) => {
  advance.mockImplementationOnce(async () => {
    owned = { ...savedPurchase, state: "preparing", reason: "purchase_pending" };
    if (firstRead === "subsequent poll") fetcher.mockResolvedValueOnce(json({ detail: { code: "unavailable" } }, 503));
    throw new TypeError("synthetic_lost_advance_reply");
  });
  renderProduct();
  await accept();

  if (firstRead === "subsequent poll") {
    expect(await screen.findByRole("alert")).toHaveTextContent(ru.Billing.errors.financialPending);
  }
  await screen.findByText(ru.Purchase.states.preparing, {}, { timeout: 4000 });
  expect(screen.getByRole("button", { name: ru.Purchase.continue })).toBeEnabled();
  expect(screen.getByRole("alert")).toHaveTextContent(ru.Billing.errors.financialPending);
  expect(advance).toHaveBeenCalledTimes(1);
  expect(bootstrap).not.toHaveBeenCalled();
});

it("keeps the expired advance request ID when an explicit status check still shows preparation", async () => {
  const requestId = "expired-advance-check";
  advance.mockImplementationOnce(async () => {
    owned = { ...savedPurchase, state: "awaiting_external_result", reason: "purchase_pending" };
    return json({ detail: { code: "preflight_deadline_exceeded", request_id: requestId } }, 503);
  });
  renderProduct();
  await accept();
  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent(requestId);

  owned = { ...savedPurchase, state: "preparing", reason: "purchase_pending" };
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: ru.Purchase.refresh })); });
  expect(screen.getByText(ru.Purchase.states.preparing)).toBeVisible();
  expect(screen.getByRole("button", { name: ru.Purchase.continue })).toBeEnabled();
  expect(screen.getByRole("alert")).toHaveTextContent(requestId);

  fetcher.mockResolvedValueOnce(json({ detail: { code: "unavailable" } }, 503));
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: ru.Purchase.refresh })); });
  expect(screen.getByRole("alert")).toHaveTextContent(requestId);

  advance.mockResolvedValueOnce(json(owned));
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: ru.Purchase.continue })); });
  expect(screen.getByRole("alert")).toHaveTextContent(requestId);
  expect(advance).toHaveBeenCalledTimes(2);
  expect(bootstrap).not.toHaveBeenCalled();
});

it("finds a late committed confirmation after a gateway failure", async () => {
  confirm.mockResolvedValueOnce(new Response("Bad Gateway", { status: 502 }));
  renderProduct();
  await accept();
  expect(await screen.findByRole("alert")).toHaveTextContent(ru.Billing.errors.financialPending);
  owned = { ...savedPurchase, state: "created" };
  expect(await screen.findByRole("button", { name: ru.Purchase.continue }, { timeout: 4000 })).toBeEnabled();
  expect(confirm).toHaveBeenCalledTimes(1);
  expect(advance).not.toHaveBeenCalled();
});

it("inspects the original purchase after a gateway timeout on advance", async () => {
  advance.mockImplementationOnce(async () => {
    owned = { ...savedPurchase, state: "preparing" };
    return new Response("Gateway Timeout", { status: 504 });
  });
  renderProduct();
  await accept();
  expect(await screen.findByText(ru.Purchase.states.preparing)).toBeVisible();
  expect(screen.getByRole("alert")).toHaveTextContent(ru.Billing.errors.financialPending);
  expect(advance).toHaveBeenCalledTimes(1);
  expect(bootstrap).not.toHaveBeenCalled();
});

it.each([
  [401, "billing_session_required", ru.Billing.errors.session],
  [403, "billing_email_verification_required", ru.Billing.errors.verification],
  [404, "purchase_not_found", ru.Billing.selectionUnavailable],
] as const)("ends product status polling on HTTP %s and allows manual inspection", async (status, code, message) => {
  vi.useFakeTimers();
  owned = { ...savedPurchase, state: "awaiting_external_result" };
  await act(async () => { renderProduct(); });
  const recover = screen.getByRole("button", { name: ru.Purchase.recover });
  const refresh = screen.getByRole("button", { name: ru.Purchase.refresh });
  recover.focus();
  expect(recover).toHaveFocus();
  fetcher.mockClear().mockResolvedValueOnce(json({ detail: { code, request_id: "read-refused" } }, status));
  await act(async () => vi.advanceTimersByTimeAsync(120_000));
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("alert")).toHaveTextContent(message);
  expect(screen.getByRole("alert")).toHaveTextContent("read-refused");
  expect(recover).not.toBeInTheDocument();
  expect(refresh).toHaveFocus();

  owned = { ...savedPurchase, state: "preparing" };
  await act(async () => { fireEvent.click(refresh); });
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: ru.Purchase.continue })).toBeEnabled();
  expect(advance).not.toHaveBeenCalled();
});

it("leaves focus on accepted terms when a pending status poll is refused", async () => {
  vi.useFakeTimers();
  owned = { ...savedPurchase, state: "preparing" };
  await act(async () => { renderProduct(); });
  screen.getByRole("button", { name: ru.Purchase.continue }).focus();
  const response = Promise.withResolvers<Response>();
  fetcher.mockClear().mockReturnValueOnce(response.promise);
  await act(async () => vi.advanceTimersByTimeAsync(2_100));
  expect(fetcher).toHaveBeenCalledTimes(1);

  const terms = screen.getByText(ru.Purchase.acceptedTerms);
  terms.focus();
  await act(async () => response.resolve(json({ detail: { code: "billing_session_required" } }, 401)));

  expect(screen.getByRole("alert")).toHaveTextContent(ru.Billing.errors.session);
  expect(terms).toHaveFocus();
});

it.each(["retry confirmation", "terms link"] as const)("handles confirmation poll refusal with focus on %s", async (focused) => {
  vi.useFakeTimers();
  confirm.mockRejectedValueOnce(new TypeError("synthetic_lost_reply"));
  await act(async () => { renderProduct(); });
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: ru.Purchase.buy })); });
  fireEvent.click(screen.getByRole("checkbox"));
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: ru.Purchase.confirm })); });

  const retry = screen.getByRole("button", { name: ru.Purchase.retryConfirm });
  const refresh = screen.getByRole("button", { name: ru.Purchase.refresh });
  retry.focus();
  expect(retry).toHaveFocus();
  const response = Promise.withResolvers<Response>();
  fetcher.mockClear().mockReturnValueOnce(response.promise);
  await act(async () => vi.advanceTimersByTimeAsync(2_100));
  expect(fetcher).toHaveBeenCalledTimes(1);
  const [input, init] = fetcher.mock.calls[0];
  expect(new URL(String(input)).pathname).toBe("/api/purchase-intents/current");
  expect(init?.method ?? "GET").toBe("GET");

  const { title, version } = purchaseReview.documents[0];
  const terms = screen.getByRole("link", { name: `${title} · ${version}` });
  if (focused === "terms link") terms.focus();
  await act(async () => response.resolve(json({ detail: { code: "billing_session_required" } }, 401)));

  expect(retry).toBeDisabled();
  expect(focused === "retry confirmation" ? refresh : terms).toHaveFocus();
  expect(confirm).toHaveBeenCalledTimes(1);
  expect(advance).not.toHaveBeenCalled();
});

it.each(["first inspection", "later poll"])("keeps frozen confirmation disabled after refusal during %s", async (when) => {
  confirm.mockImplementationOnce(async () => {
    if (when === "later poll") fetcher.mockResolvedValueOnce(json({ purchase: null }));
    fetcher.mockResolvedValueOnce(json({ detail: { code: "billing_session_required", request_id: "confirm-read" } }, 401));
    return json({ detail: { code: "internal_server_error" } }, 500);
  });
  renderProduct();
  await accept();
  await screen.findByText(ru.Billing.errors.session, {}, { timeout: 4000 });
  expect(screen.getByRole("alert")).toHaveTextContent("confirm-read");
  expect(screen.getByRole("button", { name: ru.Purchase.retryConfirm })).toBeDisabled();

  fetcher.mockResolvedValueOnce(new Response("Service Unavailable", { status: 503 }));
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: ru.Purchase.refresh })); });
  expect(screen.getByRole("button", { name: ru.Purchase.retryConfirm })).toBeDisabled();

  await act(async () => { fireEvent.click(screen.getByRole("button", { name: ru.Purchase.refresh })); });
  fireEvent.click(screen.getByRole("button", { name: ru.Purchase.retryConfirm }));
  expect(await screen.findByRole("link", { name: ru.Billing.pay })).toBeVisible();
  expect(confirm).toHaveBeenCalledTimes(2);
  expect(confirm.mock.calls[1][0].headers["Idempotency-Key"]).toBe(confirm.mock.calls[0][0].headers["Idempotency-Key"]);
});

it("keeps a typed advance refusal visible while local status still says preparing", async () => {
  advance.mockImplementationOnce(async () => {
    owned = { ...savedPurchase, state: "preparing" };
    return json({ detail: { code: "purchase_billing_not_configured", request_id: "advance-config" } }, 503);
  });
  renderProduct();
  await accept();
  expect(await screen.findByRole("alert")).toHaveTextContent(ru.Billing.errors.configuration);
  expect(await screen.findByText(ru.Purchase.states.preparing, {}, { timeout: 4000 })).toBeVisible();
  expect(screen.getByRole("alert")).toHaveTextContent("advance-config");
  expect(advance).toHaveBeenCalledTimes(1);
});
