import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AccountBilling } from "@/features/billing";
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
const open = () => fireEvent.click(screen.getByRole("button", { name: ru.Billing.open }));
const selector = () => screen.getByRole("combobox", { name: ru.Billing.selectedPurchase });
const payloads = () => bootstrap.mock.calls.map(([init]) => JSON.parse(init.body));

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
  mount.mockReset().mockImplementation((node: HTMLElement) => {
    node.append(document.createElement("iframe"));
    return () => { node.replaceChildren(); dispose(); };
  });
  dispose.mockReset();
  fetcher.mockReset().mockImplementation(async (input, init) => {
    const url = new URL(String(input));
    if (url.pathname === "/api/purchase-intents") return list(url.searchParams.get("after"));
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

it("loads a deep link locally and requires an explicit action before opening payment", async () => {
  list.mockResolvedValue(json({ purchases: [], next_cursor: null }));
  const view = renderCabinet(first.purchase_intent_id);
  await waitFor(() => expect(selector()).toHaveValue(first.purchase_intent_id));
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
  open();
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
  open();
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
  await waitFor(() => expect(screen.getByRole("button", { name: ru.Billing.open })).toBeEnabled());
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
  await waitFor(() => expect(screen.getByRole("button", { name: ru.Billing.open })).toBeEnabled());
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
  open();
  await waitFor(() => expect(mount).toHaveBeenCalledTimes(1));
  await act(async () => finish(json({ purchases: [first], next_cursor: null })));
  await screen.findByRole("article");
  expect(selector()).toHaveValue("");
  expect(payloads()).toEqual([{}]);
});

it("refuses released purchase deep links while retaining owned history separately", async () => {
  status.mockResolvedValue(json({ ...savedPurchase, state: "failed_before_external_effect", scope_held: false }));
  renderCabinet(first.purchase_intent_id);
  expect(await screen.findByRole("alert")).toHaveTextContent(ru.Billing.selectionUnavailable);
  expect(screen.getByRole("button", { name: ru.Billing.open })).toBeDisabled();
  expect(bootstrap).not.toHaveBeenCalled();
});

it("cannot mount payment for a different target returned by bootstrap", async () => {
  bootstrap.mockResolvedValue(json({ ...widgetResponse(true), payment_target: { ...widgetResponse(true).payment_target, purchase_intent_id: second.purchase_intent_id } }));
  renderCabinet(first.purchase_intent_id);
  await waitFor(() => expect(screen.getByRole("button", { name: ru.Billing.open })).toBeEnabled());
  open();
  expect(await screen.findByRole("alert")).toHaveTextContent(ru.Billing.errors.sdk);
  expect(mount).not.toHaveBeenCalled();
});
