import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AccountBilling } from "@/features/billing";
import { requestPaymentOpening } from "@/features/billing/payment-opening";
import type { AccountPurchaseResponse } from "@/generated/api-contracts/types.gen";
import ru from "@/messages/ru.json";
import pt from "@/messages/pt.json";
import { sessionChangedEvent, sessionStorageKey } from "@/shared/api/auth";
import { purchaseUser, savedPurchase, widgetResponse } from "../fixtures/purchase";
import { renderWithIntl } from "../setup/render-with-intl";

const { mount, dispose } = vi.hoisted(() => ({ mount: vi.fn(), dispose: vi.fn() }));
vi.mock("@/features/billing/official-widget-sdk", () => ({ mountOfficialWidget: mount }));
const json = (value: unknown, status = 200) => Response.json(value, { status });
const first: AccountPurchaseResponse = { purchase_intent_id: savedPurchase.purchase_intent_id, product_id: savedPurchase.product_id, state: "linked", created_at: "2026-10-27T12:00:00Z" };
const second: AccountPurchaseResponse = { ...first, purchase_intent_id: "55555555-5555-4555-8555-555555555555", product_id: "brief_decoder" };
const fetcher = vi.fn<typeof fetch>();
const list = vi.fn();
const status = vi.fn();
const bootstrap = vi.fn();
function renderCabinet(initialPurchaseId?: string, locale: "ru" | "pt" = "ru") {
  return renderWithIntl(<AccountBilling userId={purchaseUser.user_id} emailVerified initialPurchaseId={initialPurchaseId} />, { locale, messages: locale === "ru" ? ru : pt });
}
const open = (name = ru.Billing.pay) => fireEvent.click(screen.getByRole("button", { name }));
const selector = () => screen.getByRole("combobox", { name: ru.Billing.selectedPurchase });
const payloads = () => bootstrap.mock.calls.map(([init]) => JSON.parse(init.body));

it("shows a neutral selected-purchase placeholder while its deep link is loading", async () => {
  list.mockImplementationOnce(() => new Promise<Response>(() => {}));
  status.mockImplementationOnce(() => new Promise<Response>(() => {}));
  renderCabinet(first.purchase_intent_id);
  expect(selector()).toBeDisabled();
  expect(screen.getByRole("option", { name: ru.Purchase.loading })).toBeInTheDocument();
  expect(screen.queryByRole("option", { name: ru.Billing.selectionUnavailable })).not.toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

beforeEach(() => {
  window.localStorage.clear();
  window.localStorage.setItem(sessionStorageKey, "synthetic-portal-session");
  list.mockReset().mockImplementation(async () => json({ purchases: [first], next_cursor: null }));
  status.mockReset().mockImplementation(async () => json(savedPurchase));
  bootstrap.mockReset().mockImplementation(async (init: RequestInit) => {
    const body = JSON.parse(String(init.body));
    const response = widgetResponse(Boolean(body.purchase_intent_id));
    if (response.payment_target) response.payment_target.purchase_intent_id = body.purchase_intent_id;
    return json(response);
  });
  mount.mockReset().mockImplementation((node: HTMLElement, _response, _title, _current, _failure, ready: () => void) => {
    node.append(document.createElement("iframe"));
    ready();
    return () => { node.replaceChildren(); dispose(); };
  });
  dispose.mockReset();
  fetcher.mockReset().mockImplementation(async (input, init) => {
    const url = new URL(String(input));
    if (url.pathname === "/api/purchase-intents") return list(url.searchParams.get("after"));
    if (url.pathname === "/api/paid-access") return json({ access_revision: 0, grants: [], allowances: [], products: [], evidence_complete: true, committed_at: null, read_at: new Date().toISOString(), effective_until: null });
    if (url.pathname === "/api/billing/widget-bootstrap") return bootstrap(init);
    if (url.pathname.startsWith("/api/purchase-intents/")) return status();
    throw new Error("unexpected_request");
  });
  vi.stubGlobal("fetch", fetcher);
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("lists only owned brief cards and keeps catalog navigation localized", async () => {
  renderCabinet(undefined, "pt");
  const region = screen.getByRole("region", { name: pt.Account.products.title });
  const card = within(await within(region).findByRole("article"));
  expect(card.getByRole("heading", { name: "proposal_ai" })).toBeVisible();
  expect(card.getByRole("link", { name: pt.Account.products.detailAction })).toHaveAttribute("href", "/pt/products/proposal_ai");
  expect(within(region).getByRole("link", { name: pt.Account.products.allProducts })).toHaveAttribute("href", "/pt/products");
  expect(fetcher.mock.calls.some(([url]) => String(url).includes("catalog"))).toBe(false);
  expect(bootstrap).not.toHaveBeenCalled();
});

it("selects a single owned purchase and uses the same verified payment bootstrap from every entry", async () => {
  renderCabinet();
  await screen.findByRole("article");
  expect(selector()).toHaveValue(first.purchase_intent_id);
  open();
  await waitFor(() => expect(mount).toHaveBeenCalledTimes(1));
  expect(screen.getByText(/synthetic-agreement/)).toHaveTextContent("synthetic-seller");
  expect(screen.getByText("Выбранный продукт: proposal_ai")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: ru.Billing.close }));
  fireEvent.click(screen.getByRole("button", { name: ru.Purchase.manage }));
  await waitFor(() => expect(mount).toHaveBeenCalledTimes(2));
  expect(payloads()).toEqual([{ purchase_intent_id: first.purchase_intent_id }, { purchase_intent_id: first.purchase_intent_id }]);
  expect(document.querySelectorAll("iframe")).toHaveLength(1);
});

it("loads a deep link outside the first page and requires an explicit action before payment", async () => {
  const earlier = { ...second, purchase_intent_id: "33333333-3333-4333-8333-333333333333" };
  list.mockImplementation(async () => json({ purchases: [earlier], next_cursor: earlier.purchase_intent_id }));
  const view = renderCabinet(first.purchase_intent_id);
  expect(await screen.findByRole("button", { name: ru.Billing.pay })).toBeEnabled();
  expect(selector()).toHaveValue(first.purchase_intent_id);
  expect(status).toHaveBeenCalledTimes(1);
  expect(bootstrap).not.toHaveBeenCalled();
  open();
  await waitFor(() => expect(mount).toHaveBeenCalledTimes(1));
  view.unmount();
  renderCabinet(first.purchase_intent_id);
  await waitFor(() => expect(status).toHaveBeenCalledTimes(2));
  expect(bootstrap).toHaveBeenCalledTimes(1);
  expect(document.querySelectorAll("iframe")).toHaveLength(0);
});

it("consumes a verified payment click once and shows the target before Widget READY", async () => {
  const scroll = vi.spyOn(HTMLElement.prototype, "scrollIntoView");
  scroll.mockClear();
  let ready!: () => void;
  mount.mockImplementationOnce((node: HTMLElement, _response, _title, _current, _failure, onReady: () => void) => {
    node.append(document.createElement("iframe"));
    ready = onReady;
    return () => node.replaceChildren();
  });
  requestPaymentOpening(first.purchase_intent_id, purchaseUser.user_id);
  const view = render(
    <NextIntlClientProvider locale="ru" messages={ru}>
      <AccountBilling userId={purchaseUser.user_id} emailVerified initialPurchaseId={first.purchase_intent_id} />
    </NextIntlClientProvider>,
    { reactStrictMode: true }
  );
  const paymentTarget = await screen.findByText(/synthetic-agreement/);
  expect(paymentTarget).toBeVisible();
  expect(scroll).toHaveBeenCalledTimes(2);
  expect(scroll.mock.contexts[0]).toBe(screen.getByRole("region", { name: ru.Billing.title }));
  expect(scroll.mock.contexts[1]).toContainElement(paymentTarget);
  expect(scroll).toHaveBeenLastCalledWith({ behavior: "instant", block: "nearest" });
  expect(screen.getByRole("button", { name: ru.Billing.loading })).toBeDisabled();
  expect(payloads()).toEqual([{ purchase_intent_id: first.purchase_intent_id }]);
  act(() => ready());
  expect(screen.getByRole("button", { name: ru.Billing.refresh })).toBeEnabled();
  view.unmount();
  renderCabinet(first.purchase_intent_id);
  expect(await screen.findByRole("button", { name: ru.Billing.pay })).toBeEnabled();
  expect(bootstrap).toHaveBeenCalledTimes(1);
  expect(scroll).toHaveBeenCalledTimes(2);
  open();
  await waitFor(() => expect(bootstrap).toHaveBeenCalledTimes(2));
  expect(await screen.findByText(/synthetic-agreement/)).toBeVisible();
  expect(scroll).toHaveBeenCalledTimes(2);
});

it("discards a pending payment click after session replacement", async () => {
  requestPaymentOpening(first.purchase_intent_id, purchaseUser.user_id);
  window.localStorage.setItem(sessionStorageKey, "replacement-session");
  renderCabinet(first.purchase_intent_id);
  expect(await screen.findByRole("button", { name: ru.Billing.pay })).toBeEnabled();
  expect(bootstrap).not.toHaveBeenCalled();
});

it("does not transfer a claimed payment click to a new account visit", async () => {
  let finish!: (response: Response) => void;
  status.mockReturnValueOnce(new Promise<Response>((resolve) => { finish = resolve; }));
  requestPaymentOpening(first.purchase_intent_id, purchaseUser.user_id);
  const firstVisit = renderCabinet(first.purchase_intent_id);
  expect(selector()).toBeDisabled();
  firstVisit.unmount();

  renderCabinet(first.purchase_intent_id);
  await act(async () => finish(json(savedPurchase)));
  expect(await screen.findByRole("button", { name: ru.Billing.pay })).toBeEnabled();
  expect(bootstrap).not.toHaveBeenCalled();
  open();
  await waitFor(() => expect(bootstrap).toHaveBeenCalledTimes(1));
});

it("refreshes the same purchase through a fresh bootstrap and removes the old Widget while waiting", async () => {
  renderCabinet(first.purchase_intent_id);
  await waitFor(() => expect(selector()).toHaveValue(first.purchase_intent_id));
  open();
  await waitFor(() => expect(mount).toHaveBeenCalledTimes(1));
  let finish!: (response: Response) => void;
  bootstrap.mockImplementationOnce(() => new Promise<Response>((resolve) => { finish = resolve; }));
  expect(screen.getByRole("button", { name: ru.Billing.refresh })).toHaveAccessibleDescription(ru.Billing.refreshHint);
  fireEvent.click(screen.getByRole("button", { name: ru.Billing.refresh }));
  await waitFor(() => expect(bootstrap).toHaveBeenCalledTimes(2));
  expect(dispose).toHaveBeenCalledTimes(1);
  expect(document.querySelectorAll("iframe")).toHaveLength(0);
  expect(screen.getByRole("button", { name: ru.Billing.loading })).toBeDisabled();
  expect(selector()).toHaveValue(first.purchase_intent_id);
  await act(async () => finish(json(widgetResponse(true))));
  await waitFor(() => expect(mount).toHaveBeenCalledTimes(2));
  expect(payloads()).toEqual(Array(2).fill({ purchase_intent_id: first.purchase_intent_id }));
  expect(document.querySelectorAll("iframe")).toHaveLength(1);
  expect(screen.getByText(/synthetic-agreement/)).toHaveTextContent("synthetic-seller");
});

it("removes the previous Widget if refresh verification fails and retries the same purchase", async () => {
  renderCabinet(first.purchase_intent_id);
  await waitFor(() => expect(selector()).toHaveValue(first.purchase_intent_id));
  open();
  await waitFor(() => expect(mount).toHaveBeenCalledTimes(1));
  bootstrap.mockResolvedValueOnce(json({ detail: { code: "lbx_unavailable" } }, 503));
  fireEvent.click(screen.getByRole("button", { name: ru.Billing.refresh }));
  expect(await screen.findByRole("alert")).toHaveTextContent(ru.Billing.errors.unavailable);
  expect(document.querySelectorAll("iframe")).toHaveLength(0);
  expect(mount).toHaveBeenCalledTimes(1);
  open();
  await waitFor(() => expect(mount).toHaveBeenCalledTimes(2));
  expect(payloads()).toEqual(Array(3).fill({ purchase_intent_id: first.purchase_intent_id }));
});

it.each([404, 422, 503])("blocks an unavailable or foreign deep link (%s) instead of falling back to another purchase", async (code) => {
  status.mockResolvedValue(json({ detail: { code: "purchase_not_found", private: "secret" } }, code));
  renderCabinet("foreign-or-invalid");
  expect(await screen.findByRole("alert")).toHaveTextContent(ru.Billing.selectionUnavailable);
  expect(screen.getByRole("button", { name: ru.Billing.open })).toBeDisabled();
  expect(bootstrap).not.toHaveBeenCalled();
  fireEvent.change(selector(), { target: { value: first.purchase_intent_id } });
  open();
  await waitFor(() => expect(mount).toHaveBeenCalledTimes(1));
  expect(document.body).not.toHaveTextContent("secret");
});

it("disposes the previous Widget when another purchase or account viewing is selected", async () => {
  list.mockResolvedValue(json({ purchases: [first, second], next_cursor: null }));
  renderCabinet();
  await screen.findByRole("heading", { name: second.product_id });
  expect(selector()).toHaveValue("");
  open(ru.Billing.open);
  await waitFor(() => expect(mount).toHaveBeenCalledTimes(1));
  expect(mount.mock.calls[0][1].disablePayments).toBe(true);
  fireEvent.change(selector(), { target: { value: second.purchase_intent_id } });
  expect(dispose).toHaveBeenCalledTimes(1);
  expect(document.querySelectorAll("iframe")).toHaveLength(0);
  open();
  await waitFor(() => expect(mount).toHaveBeenCalledTimes(2));
  expect(payloads()).toEqual([{}, { purchase_intent_id: second.purchase_intent_id }]);
  expect(mount.mock.calls[1][1].disablePayments).toBe(false);
  expect(document.querySelectorAll("iframe")).toHaveLength(1);
});

it("shows unfinished accepted purchases for continuation without enabling payment", async () => {
  list.mockResolvedValue(json({ purchases: [{ ...first, state: "awaiting_external_result" }], next_cursor: null }));
  renderCabinet();
  const card = within(await screen.findByRole("article"));
  expect(card.getByText(ru.Account.products.pending)).toBeVisible();
  expect(card.getByRole("link", { name: ru.Purchase.continue })).toHaveAttribute("href", "/ru/products/proposal_ai");
  expect(screen.getByRole("button", { name: ru.Billing.open })).toBeDisabled();
  expect(bootstrap).not.toHaveBeenCalled();
});

it.each(["empty", "failed"])("keeps account-only viewing available with %s purchases", async (kind) => {
  list.mockImplementation(async () => kind === "empty" ? json({ purchases: [], next_cursor: null }) : json({ detail: { code: "unavailable" } }, 503));
  renderCabinet();
  await screen.findByText(kind === "empty" ? ru.Account.products.empty : ru.Account.products.unavailable);
  open(ru.Billing.open);
  await waitFor(() => expect(mount).toHaveBeenCalledTimes(1));
  expect(payloads()).toEqual([{}]);
  expect(mount.mock.calls[0][1].disablePayments).toBe(true);
});

it("pages owned purchases without dropping existing cards or selecting an arbitrary product", async () => {
  list.mockResolvedValueOnce(json({ purchases: [first], next_cursor: first.purchase_intent_id })).mockResolvedValueOnce(json({ purchases: [second], next_cursor: null }));
  renderCabinet();
  fireEvent.click(await screen.findByRole("button", { name: ru.Account.products.loadMore }));
  await screen.findByRole("heading", { name: second.product_id });
  expect(screen.getAllByRole("article")).toHaveLength(2);
  expect(list.mock.calls[1][0]).toBe(first.purchase_intent_id);
  expect(selector()).toHaveValue("");
});

it("normalizes SDK failures and retries only the same purchase", async () => {
  mount.mockImplementationOnce(() => { throw new Error("private-sdk-detail"); });
  renderCabinet(first.purchase_intent_id);
  await waitFor(() => expect(screen.getByRole("button", { name: ru.Billing.pay })).toBeEnabled());
  open();
  expect(await screen.findByRole("alert")).toHaveTextContent(ru.Billing.errors.sdk);
  open();
  await waitFor(() => expect(mount).toHaveBeenCalledTimes(2));
  expect(payloads()).toEqual([{ purchase_intent_id: first.purchase_intent_id }, { purchase_intent_id: first.purchase_intent_id }]);
});

it.each(["logout", "user", "silent_user", "selection", "unmount"])("cannot mount a late payment credential after %s changes", async (change) => {
  let finish!: (response: Response) => void;
  bootstrap.mockImplementation(() => new Promise<Response>((resolve) => { finish = resolve; }));
  const view = renderCabinet(first.purchase_intent_id);
  await waitFor(() => expect(screen.getByRole("button", { name: ru.Billing.pay })).toBeEnabled());
  open();
  await waitFor(() => expect(bootstrap).toHaveBeenCalledTimes(1));
  if (change === "unmount") view.unmount();
  else if (change === "selection") fireEvent.change(selector(), { target: { value: "" } });
  else act(() => {
    if (change === "logout") window.localStorage.clear();
    else window.localStorage.setItem(sessionStorageKey, "another-session");
    if (change !== "silent_user") window.dispatchEvent(new Event(sessionChangedEvent));
  });
  await act(async () => finish(json(widgetResponse(true))));
  expect(mount).not.toHaveBeenCalled();
});

it("keeps explicit account viewing when a delayed inventory later finds one purchase", async () => {
  let finish!: (response: Response) => void;
  list.mockImplementation(() => new Promise<Response>((resolve) => { finish = resolve; }));
  renderCabinet();
  open(ru.Billing.open);
  await waitFor(() => expect(mount).toHaveBeenCalledTimes(1));
  await act(async () => finish(json({ purchases: [first], next_cursor: null })));
  await screen.findByRole("article");
  expect(selector()).toHaveValue("");
  expect(payloads()).toEqual([{}]);
});

it("shows a released deep link separately from held purchases", async () => {
  let resolveList!: (response: Response) => void;
  list.mockReturnValueOnce(new Promise<Response>((resolve) => { resolveList = resolve; }));
  status.mockResolvedValueOnce(json({ ...savedPurchase, state: "failed_before_external_effect", scope_held: false, reason: "terms_changed" }));
  renderCabinet(first.purchase_intent_id);
  expect(await screen.findByText(ru.Purchase.states.failed_before_external_effect)).toBeVisible();
  expect(screen.getByRole("link", { name: ru.Purchase.buy })).toHaveAttribute("href", "/ru/products/proposal_ai");
  await act(async () => resolveList(json({ purchases: [{ ...first, state: "created" }], next_cursor: null })));
  expect(screen.queryByRole("article")).not.toBeInTheDocument();
  expect(screen.getByText(ru.Account.products.empty)).toBeVisible();
  expect(screen.getByRole("button", { name: ru.Billing.open })).toBeDisabled();
  expect(bootstrap).not.toHaveBeenCalled();
});

it.each([
  { entry: "unavailable", result: "terminal", leavesFocus: false },
  { entry: "unavailable", result: "unavailable", leavesFocus: false },
  { entry: "manual review", result: "terminal", leavesFocus: false },
  { entry: "manual review", result: "terminal", leavesFocus: true }
] as const)("keeps focus through a saved-link retry from $entry to $result (leaves focus: $leavesFocus)", async ({ entry, result, leavesFocus }) => {
  const pending = Promise.withResolvers<Response>();
  status
    .mockResolvedValueOnce(entry === "manual review"
      ? json({ ...savedPurchase, state: "manual_review" })
      : json({ detail: { code: "unavailable" } }, 503))
    .mockReturnValueOnce(pending.promise);
  list.mockResolvedValueOnce(json({
    purchases: entry === "manual review" ? [{ ...first, state: "manual_review" }] : [second],
    next_cursor: null
  }));
  renderCabinet(first.purchase_intent_id);
  const billing = within(screen.getByRole("region", { name: ru.Billing.title }));
  const retry = await billing.findByRole("button", { name: ru.Purchase.refresh });
  if (entry === "manual review") expect(billing.getByRole("status")).toHaveTextContent(ru.Purchase.states.manual_review);
  retry.focus();
  fireEvent.click(retry);
  expect(retry).toHaveFocus();
  expect(retry).toHaveAttribute("aria-disabled", "true");
  expect(selector()).toBeDisabled();
  expect(billing.getByRole("status")).toHaveTextContent(ru.Purchase.loading);
  expect(billing.queryByRole("alert")).not.toBeInTheDocument();
  fireEvent.click(retry);
  expect(status).toHaveBeenCalledTimes(2);

  const outside = screen.getByRole("link", { name: ru.Account.products.allProducts });
  if (leavesFocus) outside.focus();
  await act(async () => pending.resolve(result === "terminal"
    ? json({ ...savedPurchase, state: "resolved_external_terminal", scope_held: false })
    : json({ detail: { code: "unavailable", request_id: "saved-link-retry" } }, 503)));
  if (result === "terminal") {
    expect(billing.getByRole("status")).toHaveTextContent(ru.Purchase.states.resolved_external_terminal);
    expect(billing.getByRole("link", { name: ru.Purchase.buy })).toHaveAttribute("href", "/ru/products/proposal_ai");
    expect(leavesFocus ? outside : selector()).toHaveFocus();
    expect(selector()).toHaveValue(first.purchase_intent_id);
  } else {
    expect(billing.getByRole("alert")).toHaveTextContent("saved-link-retry");
    expect(retry).toHaveFocus();
    expect(retry).not.toHaveAttribute("aria-disabled", "true");
  }
  const statusRequests = fetcher.mock.calls
    .filter(([url]) => new URL(String(url)).pathname.startsWith("/api/purchase-intents/"))
    .map(([url, init]) => [new URL(String(url)).pathname, init?.method ?? "GET"]);
  expect(statusRequests).toEqual(Array(2).fill(["/api/purchase-intents/" + first.purchase_intent_id, "GET"]));
  expect(bootstrap).not.toHaveBeenCalled();
});

it("refuses a purchase deep link with a nonterminal state and a missing hold", async () => {
  status.mockResolvedValue(json({ ...savedPurchase, state: "linked", scope_held: false }));
  renderCabinet(first.purchase_intent_id);
  expect(await screen.findByRole("alert")).toHaveTextContent(ru.Billing.selectionUnavailable);
  expect(screen.getByRole("button", { name: ru.Billing.open })).toBeDisabled();
  expect(bootstrap).not.toHaveBeenCalled();
});

it.each([
  { label: "omitted", listed: [] },
  { label: "changed", listed: [{ ...first, state: "manual_review" }] },
] satisfies { label: string; listed: AccountPurchaseResponse[] }[])(
  "suspends stale payment until the $label purchase detail can be checked again", async ({ listed }) => {
    let finishList!: (value: Response) => void;
    let finishStatus!: (value: Response) => void;
    const retryReply = Promise.withResolvers<Response>();
    list.mockImplementationOnce(() => new Promise<Response>(resolve => { finishList = resolve; }));
    status.mockImplementationOnce(async () => json(savedPurchase));
    status.mockImplementationOnce(() => new Promise<Response>(resolve => { finishStatus = resolve; }));
    status.mockReturnValueOnce(retryReply.promise);
    renderCabinet(first.purchase_intent_id);
    await waitFor(() => expect(screen.getByRole("button", { name: ru.Billing.pay })).toBeEnabled());
    open(ru.Billing.pay);
    await waitFor(() => expect(mount).toHaveBeenCalledTimes(1));
    await act(async () => finishList(json({ purchases: listed, next_cursor: null })));
    await waitFor(() => expect(status).toHaveBeenCalledTimes(2));
    expect(document.querySelector("iframe")).not.toBeVisible();
    expect(screen.getByRole("button", { name: ru.Billing.refresh })).toBeDisabled();
    await act(async () => finishStatus(json({ detail: { code: "unavailable", request_id: "status-recheck" } }, 503)));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("status-recheck");
    expect(document.querySelector("iframe")).not.toBeVisible();
    const retry = within(alert).getByRole("button", { name: ru.Purchase.refresh });
    retry.focus();
    fireEvent.click(retry);
    expect(selector()).toHaveFocus();
    await waitFor(() => expect(status).toHaveBeenCalledTimes(3));
    expect(document.querySelector("iframe")).not.toBeVisible();
    await act(async () => retryReply.resolve(json({ ...savedPurchase, state: "resolved_external_terminal", scope_held: false })));
    expect(await screen.findByText(ru.Purchase.states.resolved_external_terminal)).toBeVisible();
    expect(selector()).toHaveFocus();
    expect(screen.getByRole("link", { name: ru.Purchase.buy })).toHaveAttribute("href", "/ru/products/proposal_ai");
    expect(document.querySelector("iframe")).toBeNull();
    expect(dispose).toHaveBeenCalledTimes(1);
    expect(status).toHaveBeenCalledTimes(3);
    expect(payloads()).toEqual([{ purchase_intent_id: first.purchase_intent_id }]);
  }
);

it.each(["inventory", "deep-link"])("retains a safe server request ID for %s failures and clears it after recovery", async (source) => {
  const correlation = "synthetic-cabinet-correlation";
  const failure = json({ detail: { code: "unavailable", request_id: correlation, private: "private-detail" } }, 503);
  if (source === "inventory") list.mockResolvedValueOnce(failure);
  else status.mockResolvedValueOnce(failure);
  renderCabinet(source === "deep-link" ? first.purchase_intent_id : undefined);
  const region = screen.getByRole("region", { name: source === "inventory" ? ru.Account.products.title : ru.Billing.title });
  expect(await within(region).findByRole("alert")).toHaveTextContent(correlation);
  expect(document.body).not.toHaveTextContent("private-detail");
  if (source === "inventory") fireEvent.click(within(region).getByRole("button", { name: ru.Purchase.retry }));
  else fireEvent.change(selector(), { target: { value: "" } });
  await waitFor(() => expect(within(region).queryByRole("alert")).not.toBeInTheDocument());
  expect(document.body).not.toHaveTextContent(correlation);
});

it.each(["inventory", "deep-link"])("uses the sent request ID for a %s network failure", async (source) => {
  if (source === "inventory") list.mockRejectedValueOnce(new TypeError("private-network-detail"));
  else status.mockRejectedValueOnce(new TypeError("private-network-detail"));
  renderCabinet(source === "deep-link" ? first.purchase_intent_id : undefined);
  const region = screen.getByRole("region", { name: source === "inventory" ? ru.Account.products.title : ru.Billing.title });
  const alert = await within(region).findByRole("alert");
  const request = fetcher.mock.calls.find(([url]) => source === "inventory" ? new URL(String(url)).pathname === "/api/purchase-intents" : new URL(String(url)).pathname === `/api/purchase-intents/${first.purchase_intent_id}`);
  const sent = new Headers(request?.[1]?.headers).get("X-Request-ID");
  expect(sent).toMatch(/^[a-f0-9]{32}$/);
  expect(alert).toHaveTextContent(sent!);
  expect(document.body).not.toHaveTextContent("private-network-detail");
});

it.each(["inventory", "deep-link"])("clears %s diagnostics on a session change and ignores a late failure", async (source) => {
  const correlation = "synthetic-old-session";
  let finish!: (value: Response) => void;
  const delayed = new Promise<Response>((resolve) => { finish = resolve; });
  if (source === "inventory") list.mockReturnValueOnce(delayed);
  else status.mockReturnValueOnce(delayed);
  renderCabinet(source === "deep-link" ? first.purchase_intent_id : undefined);
  await waitFor(() => expect(source === "inventory" ? list : status).toHaveBeenCalled());
  act(() => { window.localStorage.clear(); window.dispatchEvent(new Event(sessionChangedEvent)); });
  await act(async () => finish(json({ detail: { code: "unavailable", request_id: correlation } }, 503)));
  expect(document.body).not.toHaveTextContent(correlation);
  expect(document.body).not.toHaveTextContent(/Идентификатор запроса: [a-z0-9]/i);
});

it("does not display an unsafe server request ID", async () => {
  list.mockResolvedValueOnce(json({ detail: { code: "unavailable", request_id: "private unsafe<value>" } }, 503));
  renderCabinet();
  const alert = await within(screen.getByRole("region", { name: ru.Account.products.title })).findByRole("alert");
  expect(alert).not.toHaveTextContent("private unsafe");
  const request = fetcher.mock.calls.find(([url]) => new URL(String(url)).pathname === "/api/purchase-intents");
  expect(alert).toHaveTextContent(new Headers(request?.[1]?.headers).get("X-Request-ID")!);
});

it.each(["linked", "awaiting_external_result"] as const)("keeps the freshly linked purchase in sync when an older list response arrives after a %s point read", async (initialState) => {
  let resolveList!: (response: Response) => void;
  list.mockReturnValueOnce(new Promise<Response>((resolve) => { resolveList = resolve; }));
  status.mockImplementationOnce(async () => json({ ...savedPurchase, state: initialState }));
  renderCabinet(first.purchase_intent_id);
  if (initialState === "awaiting_external_result") {
    expect(await screen.findByText(ru.Billing.preparationRequired, { exact: false })).toBeVisible();
  }

  expect(await screen.findByRole("button", { name: ru.Billing.pay }, { timeout: 3000 })).toBeEnabled();
  await act(async () => resolveList(json({ purchases: [{ ...first, state: "awaiting_external_result" }], next_cursor: null })));

  const card = await screen.findByRole("article");
  expect(await within(card).findByText(ru.Account.products.prepared)).toBeVisible();
  expect(within(card).queryByText(ru.Account.products.pending)).not.toBeInTheDocument();
});

it.each(["before", "after"] as const)("uses the current status when an earlier linked point read finishes %s the list retry", async (pointResponse) => {
  let resolveStatus!: (response: Response) => void;
  list.mockResolvedValueOnce(json({ detail: { code: "unavailable" } }, 503));
  status.mockReturnValueOnce(new Promise<Response>((resolve) => { resolveStatus = resolve; }));
  status.mockImplementation(async () => json({ ...savedPurchase, state: "manual_review" }));
  if (pointResponse === "after") requestPaymentOpening(first.purchase_intent_id, purchaseUser.user_id);
  renderCabinet(first.purchase_intent_id);
  const retry = await screen.findByRole("button", { name: ru.Purchase.retry });

  if (pointResponse === "before") await act(async () => resolveStatus(json(savedPurchase)));
  list.mockResolvedValueOnce(json({ purchases: [{ ...first, state: "manual_review" }], next_cursor: null }));
  fireEvent.click(retry);
  const card = await screen.findByRole("article");
  if (pointResponse === "after") await act(async () => resolveStatus(json(savedPurchase)));

  expect(await within(card).findByText(ru.Account.products.pending)).toBeVisible();
  expect(within(card).queryByRole("button", { name: ru.Purchase.manage })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: ru.Billing.pay })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: ru.Billing.open })).toBeDisabled();
  expect(bootstrap).not.toHaveBeenCalled();
  expect(status).toHaveBeenCalledTimes(pointResponse === "before" ? 1 : 2);
});

it.each(["complete", "partial"] as const)("uses absence from a newer %s purchase list only when the list covers the account", async (coverage) => {
  list.mockResolvedValueOnce(json({ detail: { code: "unavailable" } }, 503));
  status.mockResolvedValueOnce(json({ ...savedPurchase, state: "created" }));
  renderCabinet(first.purchase_intent_id);
  const billing = within(screen.getByRole("region", { name: ru.Billing.title }));
  expect(await billing.findByRole("link", { name: ru.Purchase.continue })).toBeVisible();

  list.mockResolvedValueOnce(json({ purchases: [second], next_cursor: coverage === "partial" ? second.purchase_intent_id : null }));
  fireEvent.click(screen.getByRole("button", { name: ru.Purchase.retry }));
  await screen.findByRole("heading", { name: second.product_id });

  if (coverage === "complete") {
    expect(billing.getByRole("alert")).toHaveTextContent(ru.Billing.selectionUnavailable);
    expect(billing.queryByRole("link", { name: ru.Purchase.continue })).not.toBeInTheDocument();
  } else {
    expect(billing.getByRole("link", { name: ru.Purchase.continue })).toBeVisible();
  }
});

it.each([false, true])("reconciles overlapping reads when the first list request reads the newer database state (transient failure: %s)", async (transientFailure) => {
  let permitListRead!: () => void;
  const beforeListRead = new Promise<void>((resolve) => { permitListRead = resolve; });
  let persistedState: AccountPurchaseResponse["state"] = "linked";
  list.mockImplementationOnce(async () => {
    await beforeListRead;
    return json({ purchases: [{ ...first, state: persistedState }], next_cursor: null });
  });
  status.mockImplementation(async () => json({ ...savedPurchase, state: persistedState }));
  if (transientFailure) {
    status.mockResolvedValueOnce(json(savedPurchase));
    status.mockResolvedValueOnce(json({ detail: { code: "unavailable" } }, 503));
  }
  renderCabinet(first.purchase_intent_id);
  expect(await screen.findByRole("button", { name: ru.Billing.pay })).toBeEnabled();
  expect(list).toHaveBeenCalledTimes(1);

  // Reconciliation commits after the point GET read and before the parked list reads.
  persistedState = "manual_review";
  await act(async () => permitListRead());
  expect(screen.queryByRole("button", { name: ru.Billing.pay })).not.toBeInTheDocument();
  const card = await screen.findByRole("article");
  expect(await within(card).findByText(ru.Account.products.pending, {}, { timeout: 4000 })).toBeVisible();
  expect(within(card).queryByRole("button", { name: ru.Purchase.manage })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: ru.Billing.pay })).not.toBeInTheDocument();
  expect(status).toHaveBeenCalledTimes(transientFailure ? 3 : 2);
  expect(bootstrap).not.toHaveBeenCalled();
});

it("keeps observing recovery when an already-started poll reads a linked purchase after a list retry", async () => {
  vi.useFakeTimers();
  try {
    let permitPollRead!: () => void;
    const beforePollRead = new Promise<void>((resolve) => { permitPollRead = resolve; });
    let persistedState: AccountPurchaseResponse["state"] = "awaiting_external_result";
    list.mockResolvedValueOnce(json({ detail: { code: "unavailable" } }, 503));
    status
      .mockImplementationOnce(async () => json({ ...savedPurchase, state: persistedState }))
      .mockImplementationOnce(async () => {
        await beforePollRead;
        return json({ ...savedPurchase, state: persistedState });
      })
      .mockImplementation(async () => json({ ...savedPurchase, state: persistedState }));

    await act(async () => { renderCabinet(first.purchase_intent_id); });
    expect(screen.getByRole("button", { name: ru.Billing.open })).toBeDisabled();
    await act(async () => vi.advanceTimersByTimeAsync(2100));
    expect(status).toHaveBeenCalledTimes(2);

    list.mockImplementationOnce(async () => json({ purchases: [{ ...first, state: persistedState }], next_cursor: null }));
    await act(async () => fireEvent.click(screen.getByRole("button", { name: ru.Purchase.retry })));
    expect(screen.getByText(ru.Account.products.pending)).toBeVisible();
    const billing = within(screen.getByRole("region", { name: ru.Billing.title }));
    const continuation = billing.getByRole("link", { name: ru.Purchase.continue });
    continuation.focus();
    expect(continuation).toHaveFocus();

    // The worker commits after the list query. The poll reads after that commit.
    persistedState = "linked";
    await act(async () => permitPollRead());
    await act(async () => vi.advanceTimersByTimeAsync(12_000));
    const payment = billing.getByRole("button", { name: ru.Billing.pay });
    expect(payment).toBeEnabled();
    expect(payment).toHaveFocus();
    expect(screen.getByText(ru.Account.products.prepared)).toBeVisible();
    expect(bootstrap).not.toHaveBeenCalled();
  } finally {
    vi.useRealTimers();
  }
});

it("clears the pause notice when polling resumes for the same purchase", async () => {
  vi.useFakeTimers();
  try {
    let persistedState: AccountPurchaseResponse["state"] = "preparing";
    list.mockResolvedValueOnce(json({}, 503));
    list.mockImplementation(async () => json({ purchases: [{ ...first, state: persistedState }], next_cursor: null }));
    status.mockImplementation(async () => json({ ...savedPurchase, state: persistedState }));

    await act(async () => { renderCabinet(first.purchase_intent_id); });
    await act(async () => vi.advanceTimersByTimeAsync(120_001));
    expect(screen.getByText(ru.Purchase.statusPollingPaused)).toBeVisible();

    persistedState = "awaiting_external_result";
    const readsBeforeRestart = status.mock.calls.length;
    await act(async () => fireEvent.click(screen.getByRole("button", { name: ru.Purchase.retry })));
    await act(async () => vi.advanceTimersByTimeAsync(2100));
    expect(status).toHaveBeenCalledTimes(readsBeforeRestart + 1);
    expect(screen.queryByText(ru.Purchase.statusPollingPaused)).not.toBeInTheDocument();
  } finally {
    vi.useRealTimers();
  }
});

it.each([
  [401, "opening"], [403, "open"]
] as const)("closes the payment Widget on HTTP %i while it is %s", async (code, phase) => {
  const inventory = Promise.withResolvers<Response>();
  const opening = Promise.withResolvers<Response>();
  list.mockReturnValueOnce(inventory.promise);
  bootstrap.mockReturnValueOnce(opening.promise);
  status.mockResolvedValueOnce(json(savedPurchase)).mockResolvedValueOnce(json({ detail: {
    code: code === 401 ? "billing_session_required" : "billing_email_verification_required"
  } }, code));
  renderCabinet(first.purchase_intent_id);
  fireEvent.click(await screen.findByRole("button", { name: ru.Billing.pay }));
  await waitFor(() => expect(bootstrap).toHaveBeenCalledTimes(1));

  if (phase === "open") {
    await act(async () => opening.resolve(json(widgetResponse(true))));
    expect(document.querySelector("iframe")).toBeVisible();
  }
  await act(async () => inventory.resolve(json({ purchases: [{ ...first, state: "manual_review" }], next_cursor: null })));
  expect(await screen.findByText(code === 401 ? ru.Billing.errors.session : ru.Billing.errors.verification)).toBeVisible();
  if (phase === "opening") await act(async () => opening.resolve(json(widgetResponse(true))));

  expect(document.querySelector("iframe")).toBeNull();
  expect(mount).toHaveBeenCalledTimes(phase === "open" ? 1 : 0);
  expect(screen.getByRole("button", { name: ru.Billing.open })).toBeDisabled();
});

it.each([
  ["manual_review", "opening"], ["not_found", "open"]
] as const)("closes payment for a confirmed %s purchase while the Widget is %s", async (result, phase) => {
  const inventory = Promise.withResolvers<Response>();
  const opening = Promise.withResolvers<Response>();
  list.mockReturnValueOnce(inventory.promise);
  bootstrap.mockReturnValueOnce(opening.promise);
  status.mockResolvedValueOnce(json(savedPurchase)).mockResolvedValueOnce(result === "manual_review"
    ? json({ ...savedPurchase, state: "manual_review" })
    : json({ detail: { code: "purchase_not_found" } }, 404));
  renderCabinet(first.purchase_intent_id);
  fireEvent.click(await screen.findByRole("button", { name: ru.Billing.pay }));
  await waitFor(() => expect(bootstrap).toHaveBeenCalledTimes(1));

  if (phase === "open") {
    await act(async () => opening.resolve(json(widgetResponse(true))));
    expect(document.querySelector("iframe")).toBeVisible();
  }
  const focused = document.querySelector("iframe") ?? screen.getByRole("button", { name: ru.Billing.close });
  focused.focus();
  expect(focused).toHaveFocus();
  await act(async () => inventory.resolve(json({ purchases: [{ ...first, state: "manual_review" }], next_cursor: null })));
  await screen.findByText(result === "manual_review" ? ru.Purchase.states.manual_review : ru.Billing.selectionUnavailable, {
    selector: "p", exact: false
  });
  if (phase === "opening") await act(async () => opening.resolve(json(widgetResponse(true))));

  expect(document.querySelector("iframe")).toBeNull();
  expect(mount).toHaveBeenCalledTimes(phase === "open" ? 1 : 0);
  expect(selector()).toHaveFocus();
});

it("keeps the payment Widget mounted through a transient status failure and resumes it after a fresh check", async () => {
  const inventory = Promise.withResolvers<Response>();
  list.mockReturnValueOnce(inventory.promise);
  status.mockResolvedValueOnce(json(savedPurchase)).mockResolvedValueOnce(json({ detail: { code: "unavailable" } }, 503));
  renderCabinet(first.purchase_intent_id);
  fireEvent.click(await screen.findByRole("button", { name: ru.Billing.pay }));
  await waitFor(() => expect(mount).toHaveBeenCalledTimes(1));

  await act(async () => inventory.resolve(json({ purchases: [{ ...first, state: "manual_review" }], next_cursor: null })));
  await waitFor(() => expect(status).toHaveBeenCalledTimes(2));
  const iframe = document.querySelector("iframe");
  expect(iframe).not.toBeVisible();
  await waitFor(() => expect(iframe).toBeVisible(), { timeout: 4000 });
  expect(mount).toHaveBeenCalledTimes(1);
  expect(dispose).not.toHaveBeenCalled();
});

it.each(["manual_review", "session_refused", "stale_conflict"] as const)(
  "handles a pending status read returning %s after a list retry makes the same purchase payable",
  async (result) => {
    const pending = Promise.withResolvers<Response>();
    const needsReview = { ...savedPurchase, state: "manual_review" };
    list.mockResolvedValueOnce(json({ detail: { code: "unavailable" } }, 503));
    status.mockResolvedValueOnce(json({ ...savedPurchase, state: "awaiting_external_result" }));
    status.mockReturnValueOnce(pending.promise);
    if (result === "manual_review") status.mockResolvedValueOnce(json(needsReview));

    renderCabinet(first.purchase_intent_id);
    const retry = await screen.findByRole("button", { name: ru.Purchase.retry });
    await waitFor(() => expect(status).toHaveBeenCalledTimes(2), { timeout: 3500 });
    fireEvent.click(retry);
    fireEvent.click(await screen.findByRole("button", { name: ru.Billing.pay }));
    await waitFor(() => expect(document.querySelector("iframe")).toBeVisible());

    await act(async () => pending.resolve(result === "session_refused"
      ? json({ detail: { code: "billing_session_required" } }, 401)
      : json(needsReview)));

    if (result === "session_refused") {
      expect(screen.getByRole("alert")).toHaveTextContent(ru.Billing.errors.session);
    } else {
      // The pending point read overlapped the list retry. Confirm which state is current.
      await waitFor(() => expect(status).toHaveBeenCalledTimes(3));
    }
    if (result === "stale_conflict") {
      expect(screen.getByRole("button", { name: ru.Billing.refresh })).toBeEnabled();
      expect(document.querySelector("iframe")).toBeVisible();
    } else {
      await waitFor(() => expect(document.querySelector("iframe")).toBeNull());
    }
    expect(bootstrap).toHaveBeenCalledTimes(1);
  }
);

it("closes the Widget when retrying the purchase list reveals an expired session", async () => {
  list.mockResolvedValueOnce(json({}, 503));
  render(<button type="button">Outside checkout</button>);
  const outside = screen.getByRole("button", { name: "Outside checkout" });
  renderCabinet(first.purchase_intent_id);
  const retry = await screen.findByRole("button", { name: ru.Purchase.retry });
  fireEvent.click(await screen.findByRole("button", { name: ru.Billing.pay }));
  await waitFor(() => expect(document.querySelector("iframe")).toBeVisible());
  outside.focus();
  list.mockResolvedValueOnce(json({ detail: { code: "billing_session_required", request_id: "list-auth" } }, 401));
  fireEvent.click(retry);
  const billing = within(screen.getByRole("region", { name: ru.Billing.title }));
  expect(await billing.findByRole("alert")).toHaveTextContent(ru.Billing.errors.session);
  expect(billing.getByRole("alert")).toHaveTextContent("list-auth");
  expect(document.querySelector("iframe")).toBeNull();
  expect(outside).toHaveFocus();
  expect(bootstrap).toHaveBeenCalledTimes(1);
});

it.each([
  ["/api/paid-access", 401, "billing_session_required", ru.Billing.errors.session],
  ["/api/paid-usage", 403, "billing_email_verification_required", ru.Billing.errors.verification],
  ["/api/paid-access", 503, "paid_access_state_pending", null],
  ["/api/paid-usage", 403, "lbx_scope_forbidden", null],
] as const)("handles %s returning %i during checkout", async (path, code, reason, message) => {
  vi.useFakeTimers();
  try {
    await act(async () => { renderCabinet(first.purchase_intent_id); });
    await act(async () => open());
    expect(document.querySelector("iframe")).toBeVisible();
    const close = screen.getByRole("button", { name: ru.Billing.close });
    close.focus();
    expect(close).toHaveFocus();
    const ordinaryFetch = fetcher.getMockImplementation()!;
    fetcher.mockClear().mockImplementation((input, init) => new URL(String(input)).pathname === path
      ? Promise.resolve(json({ detail: { code: reason, request_id: "paid-read" } }, code))
      : ordinaryFetch(input, init));
    await act(async () => vi.advanceTimersByTimeAsync(30_000));
    expect(fetcher.mock.calls.some(([input]) => new URL(String(input)).pathname === path)).toBe(true);
    const billing = within(screen.getByRole("region", { name: ru.Billing.title }));
    if (message) {
      expect(document.querySelector("iframe")).toBeNull();
      expect(billing.getByRole("alert")).toHaveTextContent(message);
      expect(billing.getByRole("alert")).toHaveTextContent("paid-read");
      expect(billing.queryByRole("combobox")).toBeNull();
      expect(screen.getByRole("region", { name: ru.Billing.title })).not.toHaveTextContent(first.product_id);
      expect(billing.getByRole("button", { name: ru.Billing.open })).toBeDisabled();
      expect(billing.getByRole("button", { name: ru.Purchase.retry })).toHaveFocus();
    } else {
      expect(document.querySelector("iframe")).toBeVisible();
      expect(billing.queryByRole("alert")).toBeNull();
      expect(close).toHaveFocus();
    }
    expect(bootstrap).toHaveBeenCalledTimes(1);
  } finally {
    vi.useRealTimers();
  }
});

it("discards the pending payment click when a cabinet read refuses the session before the selected purchase arrives", async () => {
  const point = Promise.withResolvers<Response>();
  status.mockReturnValueOnce(point.promise);
  list.mockResolvedValueOnce(json({ detail: { code: "billing_session_required" } }, 401));
  requestPaymentOpening(first.purchase_intent_id, purchaseUser.user_id);
  renderCabinet(first.purchase_intent_id);
  await act(async () => point.resolve(json(savedPurchase)));
  expect(bootstrap).not.toHaveBeenCalled();
  const billing = within(screen.getByRole("region", { name: ru.Billing.title }));
  expect(billing.getByRole("alert")).toHaveTextContent(ru.Billing.errors.session);
});

it.each([
  { scenario: "an outdated purchase status", code: 200 },
  { scenario: "a missing previous purchase", code: 404, reason: "purchase_not_found" },
  { scenario: "an unclassified 401", code: 401, reason: "unexpected_auth_error" },
  { scenario: "a late verification refusal", code: 403, reason: "billing_email_verification_required" },
  { scenario: "a refusal of the current session", code: 401, reason: "billing_session_required", closesCheckout: true },
  { scenario: "a refusal of a replaced session", code: 401, reason: "billing_session_required", replacesSession: true },
])("handles $scenario from a pending recheck after changing purchases", async ({ code, reason, closesCheckout, replacesSession }) => {
  let finishInitial!: (response: Response) => void;
  let finishRecheck!: (response: Response) => void;
  list.mockResolvedValueOnce(json({
    purchases: [{ ...first, state: "manual_review" }, second], next_cursor: null
  }));
  status
    .mockReturnValueOnce(new Promise<Response>((resolve) => { finishInitial = resolve; }))
    .mockReturnValueOnce(new Promise<Response>((resolve) => { finishRecheck = resolve; }));
  requestPaymentOpening(first.purchase_intent_id, purchaseUser.user_id);
  const cabinet = renderCabinet(first.purchase_intent_id);
  await screen.findByRole("heading", { name: second.product_id });
  await act(async () => finishInitial(json(savedPurchase)));
  await waitFor(() => expect(status).toHaveBeenCalledTimes(2));
  expect(bootstrap).not.toHaveBeenCalled();

  if (replacesSession) {
    act(() => {
      window.localStorage.setItem(sessionStorageKey, "replacement-session");
      window.dispatchEvent(new Event(sessionChangedEvent));
    });
    cabinet.unmount();
    list.mockResolvedValueOnce(json({ purchases: [second], next_cursor: null }));
    renderCabinet();
  } else {
    fireEvent.change(selector(), { target: { value: second.purchase_intent_id } });
  }
  fireEvent.click(await screen.findByRole("button", { name: ru.Billing.pay }));
  await waitFor(() => expect(mount).toHaveBeenCalledTimes(1));
  expect(document.querySelector("iframe")).toBeVisible();
  await act(async () => finishRecheck(code === 200
    ? json(savedPurchase)
    : json({ detail: { code: reason, request_id: "old-selection" } }, code)));

  if (closesCheckout) {
    expect(document.querySelector("iframe")).toBeNull();
    expect(screen.getByRole("alert")).toHaveTextContent(ru.Billing.errors.session);
    expect(screen.getByRole("alert")).toHaveTextContent("old-selection");
  } else {
    expect(screen.queryByText("old-selection", { exact: false })).not.toBeInTheDocument();
    expect(selector()).toHaveValue(second.purchase_intent_id);
    expect(document.querySelector("iframe")).toBeVisible();
  }
  expect(payloads()).toEqual([{ purchase_intent_id: second.purchase_intent_id }]);
});

it("closes checkout on a current-session refusal from the initial purchase read after opening another purchase", async () => {
  const point = Promise.withResolvers<Response>();
  status.mockReturnValueOnce(point.promise);
  list.mockResolvedValueOnce(json({ purchases: [first, second], next_cursor: null }));
  renderCabinet(first.purchase_intent_id);
  const otherProduct = await screen.findByRole("heading", { name: second.product_id });
  expect(status).toHaveBeenCalledTimes(1);

  fireEvent.click(within(otherProduct.closest("article")!).getByRole("button", { name: ru.Purchase.manage }));
  await waitFor(() => expect(document.querySelector("iframe")).toBeVisible());

  await act(async () => point.resolve(json({ detail: { code: "billing_session_required", request_id: "initial-read-refusal" } }, 401)));

  expect(document.querySelector("iframe")).toBeNull();
  const alert = screen.getByRole("alert");
  expect(alert).toHaveTextContent(ru.Billing.errors.session);
  expect(alert).toHaveTextContent("initial-read-refusal");
  expect(payloads()).toEqual([{ purchase_intent_id: second.purchase_intent_id }]);
});

it.each(["open", "opening"])("closes an %s checkout on a late bootstrap refusal of the current session", async (checkout) => {
  const previous = Promise.withResolvers<Response>();
  const replacement = Promise.withResolvers<Response>();
  bootstrap.mockReturnValueOnce(previous.promise).mockReturnValueOnce(replacement.promise);
  list.mockResolvedValueOnce(json({ purchases: [first, second], next_cursor: null }));
  requestPaymentOpening(first.purchase_intent_id, purchaseUser.user_id);
  renderCabinet(first.purchase_intent_id);
  await waitFor(() => expect(bootstrap).toHaveBeenCalledTimes(1));

  fireEvent.change(selector(), { target: { value: second.purchase_intent_id } });
  open();
  const response = widgetResponse(true);
  response.payment_target!.purchase_intent_id = second.purchase_intent_id;
  if (checkout === "open") {
    await act(async () => replacement.resolve(json(response)));
    expect(document.querySelector("iframe")).toBeVisible();
  } else {
    expect(screen.getByRole("button", { name: ru.Billing.loading })).toBeDisabled();
  }

  const focused = checkout === "open" ? document.querySelector("iframe")! : screen.getByRole("button", { name: ru.Billing.close });
  focused.focus();
  expect(focused).toHaveFocus();
  await act(async () => previous.resolve(json({
    detail: { code: "billing_session_required", request_id: "bootstrap-refusal" }
  }, 401)));
  if (checkout === "opening") await act(async () => replacement.resolve(json(response)));

  expect(document.querySelector("iframe")).toBeNull();
  expect(mount).toHaveBeenCalledTimes(checkout === "open" ? 1 : 0);
  expect(screen.getByRole("alert")).toHaveTextContent(ru.Billing.errors.session);
  expect(screen.getByRole("alert")).toHaveTextContent("bootstrap-refusal");
  expect(screen.getByRole("button", { name: ru.Billing.open })).toBeDisabled();
  expect(screen.getByRole("button", { name: ru.Purchase.retry })).toHaveFocus();
  expect(payloads()).toEqual([
    { purchase_intent_id: first.purchase_intent_id }, { purchase_intent_id: second.purchase_intent_id }
  ]);
});

it.each([
  { scenario: "an unclassified 401", code: "unexpected_auth_error" },
  { scenario: "a refusal of the replaced session", code: "billing_session_required", replacesSession: true }
])("keeps the next checkout open after $scenario from a previous bootstrap", async ({ code, replacesSession }) => {
  const previous = Promise.withResolvers<Response>();
  bootstrap.mockReturnValueOnce(previous.promise);
  list.mockImplementation(async () => json({ purchases: [first, second], next_cursor: null }));
  requestPaymentOpening(first.purchase_intent_id, purchaseUser.user_id);
  const cabinet = renderCabinet(first.purchase_intent_id);
  await waitFor(() => expect(bootstrap).toHaveBeenCalledTimes(1));

  if (replacesSession) {
    act(() => {
      window.localStorage.setItem(sessionStorageKey, "replacement-session");
      window.dispatchEvent(new Event(sessionChangedEvent));
    });
    cabinet.unmount();
    renderCabinet();
    await screen.findByRole("heading", { name: second.product_id });
  }
  fireEvent.change(selector(), { target: { value: second.purchase_intent_id } });
  open();
  await screen.findByRole("button", { name: ru.Billing.refresh });

  await act(async () => previous.resolve(json({ detail: { code, request_id: "old-bootstrap" } }, 401)));
  expect(document.querySelector("iframe")).toBeVisible();
  expect(selector()).toHaveValue(second.purchase_intent_id);
  expect(screen.queryByText("old-bootstrap", { exact: false })).not.toBeInTheDocument();
});

it("keeps an explicitly selected purchase visible after polling observes its release", async () => {
  vi.useFakeTimers();
  try {
    list.mockResolvedValueOnce(json({ purchases: [{ ...first, state: "awaiting_external_result" }, second], next_cursor: null }));
    status.mockResolvedValueOnce(json({ ...savedPurchase, state: "resolved_external_terminal", scope_held: false }));
    await act(async () => { renderCabinet(); });
    fireEvent.change(selector(), { target: { value: first.purchase_intent_id } });
    await act(async () => vi.advanceTimersByTimeAsync(2100));
    const billing = within(screen.getByRole("region", { name: ru.Billing.title }));
    expect(billing.getByText(ru.Purchase.states.resolved_external_terminal)).toBeVisible();
    expect(selector()).toHaveValue(first.purchase_intent_id);
    expect(billing.getByRole("link", { name: ru.Purchase.buy })).toHaveAttribute("href", "/ru/products/proposal_ai");
    expect(screen.getAllByRole("article")).toHaveLength(1);
    expect(bootstrap).not.toHaveBeenCalled();
  } finally {
    vi.useRealTimers();
  }
});
