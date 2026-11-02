import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AccountBilling } from "@/features/billing";
import { paidAccessRefreshMs } from "@/features/billing/use-paid-access";
import ru from "@/messages/ru.json";
import { sessionChangedEvent, sessionStorageKey } from "@/shared/api/auth";
import { paidState } from "../fixtures/paid-access";
import { purchaseUser, savedPurchase, widgetResponse } from "../fixtures/purchase";
import { renderWithIntl } from "../setup/render-with-intl";

const mount = vi.hoisted(() => vi.fn());
vi.mock("@/features/billing/official-widget-sdk", () => ({ mountOfficialWidget: mount }));
const paid = vi.fn();
const fetcher = vi.fn<typeof fetch>();
const a = ru.Account.products.paid;
const purchase = { purchase_intent_id: savedPurchase.purchase_intent_id, product_id: "proposal_ai", state: "linked", created_at: "2026-10-27T12:00:00Z" };
function renderCabinet(userId = purchaseUser.user_id, emailVerified = true) {
  return renderWithIntl(<AccountBilling userId={userId} emailVerified={emailVerified} />, { locale: "ru", messages: ru });
}
const refresh = () => fireEvent.click(screen.getByRole("button", { name: a.refresh }));
beforeEach(() => {
  window.localStorage.setItem(sessionStorageKey, "synthetic-paid-session");
  paid.mockReset().mockImplementation(async () => Response.json(paidState()));
  mount.mockReset().mockReturnValue(() => {});
  fetcher.mockReset().mockImplementation(async (input) => {
    const path = new URL(String(input)).pathname;
    if (path === "/api/paid-access") return paid();
    if (path === "/api/purchase-intents") return Response.json({ purchases: [purchase], next_cursor: null });
    if (path === "/api/billing/widget-bootstrap") return Response.json(widgetResponse(true));
    throw new Error("unexpected_request");
  });
  vi.stubGlobal("fetch", fetcher);
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); window.localStorage.clear(); });

it("shows committed access and purchased quantity separately from preparation and unavailable usage", async () => {
  renderCabinet();
  const card = within(await screen.findByRole("article"));
  expect(await card.findByText(a.confirmed)).toBeVisible();
  expect(card.getByText("Приобретённый лимит: 100 generation")).toBeVisible();
  expect(card.getByText(a.simulated)).toBeVisible();
  expect(card.getByText(a.usageUnavailable)).toBeVisible();
  expect(card.getByText(ru.Account.products.prepared)).toBeVisible();
  expect(document.body).not.toHaveTextContent(/unlimited|безлимит|осталось: 0|использовано: 0/i);
  expect(fetcher.mock.calls.every(([url]) => !String(url).includes("catalog"))).toBe(true);
});

it.each(["no_paid_access", "unavailable"] as const)("keeps empty effective contents separate from %s product evidence", async (status) => {
  paid.mockImplementation(async () => Response.json(paidState({ access_revision: 2, grants: [], allowances: [], products: [{ product_id: "proposal_ai", status, observed_at: null, effective_until: null }], effective_until: null })));
  renderCabinet();
  const card = within(await screen.findByRole("article"));
  expect(await card.findByText(a[status])).toBeVisible();
  expect(card.queryByText(a.confirmed)).not.toBeInTheDocument();
  expect(card.getByText(a.usageUnavailable)).toBeVisible();
});

it("preserves independent paid products even if purchase inventory is unavailable", async () => {
  fetcher.mockImplementation(async (input) => new URL(String(input)).pathname === "/api/paid-access"
    ? Response.json(paidState({ grants: [{ product_id: "proposal_ai", valid_until: null }, { product_id: "brief_decoder", valid_until: null }] }))
    : Response.json({ detail: { code: "unavailable" } }, { status: 503 }));
  renderCabinet();
  await screen.findByRole("heading", { name: "brief_decoder" });
  expect(screen.getAllByText(a.confirmed)).toHaveLength(2);
  expect(screen.getByText(a.meteringUnavailable)).toBeVisible();
});

it("refuses overdue responses, shows correlation and retries only the local API", async () => {
  paid.mockResolvedValueOnce(Response.json({ detail: { code: "paid_access_deadline_pending", request_id: "safe-paid-read-id", private: "private-detail" } }, { status: 503 }));
  renderCabinet();
  expect(await screen.findByRole("alert")).toHaveTextContent(a.deadlinePending);
  expect(screen.getByRole("alert")).toHaveTextContent("safe-paid-read-id");
  expect(document.body).not.toHaveTextContent("private-detail");
  refresh();
  expect(await screen.findByText(a.confirmed)).toBeVisible();
  expect(paid).toHaveBeenCalledTimes(2);
});

it.each(["logout", "replacement", "silent", "unmount"])("ignores late state and stops refresh after %s", async (change) => {
  let finish!: (response: Response) => void;
  paid.mockImplementationOnce(() => new Promise<Response>((resolve) => { finish = resolve; }));
  const view = renderCabinet();
  await waitFor(() => expect(paid).toHaveBeenCalledTimes(1));
  if (change === "unmount") view.unmount();
  else act(() => {
    if (change === "logout") window.localStorage.clear();
    else window.localStorage.setItem(sessionStorageKey, "another-session");
    if (change !== "silent") window.dispatchEvent(new Event(sessionChangedEvent));
  });
  await act(async () => finish(Response.json(paidState())));
  expect(screen.queryByText(a.confirmed)).not.toBeInTheDocument();
  vi.useFakeTimers();
  await act(async () => vi.advanceTimersByTimeAsync(paidAccessRefreshMs * 2));
  expect(paid).toHaveBeenCalledTimes(1);
});

it("refreshes while visible, pauses while hidden and catches up on visibility", async () => {
  vi.useFakeTimers();
  renderCabinet();
  await act(async () => vi.advanceTimersByTimeAsync(1));
  expect(screen.getByText(a.confirmed)).toBeVisible();
  await act(async () => vi.advanceTimersByTimeAsync(paidAccessRefreshMs));
  expect(paid).toHaveBeenCalledTimes(2);
  const visibility = vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
  act(() => document.dispatchEvent(new Event("visibilitychange")));
  await act(async () => vi.advanceTimersByTimeAsync(paidAccessRefreshMs * 2));
  expect(paid).toHaveBeenCalledTimes(2);
  visibility.mockReturnValue("visible");
  await act(async () => document.dispatchEvent(new Event("visibilitychange")));
  expect(paid).toHaveBeenCalledTimes(3);
});

it("expires a successful view at its server deadline even before the next periodic refresh", async () => {
  vi.useFakeTimers();
  paid.mockResolvedValueOnce(Response.json(paidState({ effective_until: new Date(Date.now() + 500).toISOString() })))
    .mockResolvedValue(Response.json({ detail: { code: "paid_access_deadline_pending" } }, { status: 503 }));
  renderCabinet();
  await act(async () => vi.advanceTimersByTimeAsync(1));
  expect(screen.getByText(a.confirmed)).toBeVisible();
  await act(async () => vi.advanceTimersByTimeAsync(510));
  expect(screen.queryByText(a.confirmed)).not.toBeInTheDocument();
  expect(screen.getByRole("alert")).toHaveTextContent(a.deadlinePending);
});

it("a Widget close refreshes saved paid state without browser-derived grants or purchase advances", async () => {
  paid.mockImplementation(async () => Response.json(paidState({ access_revision: 0, grants: [], allowances: [], products: [{ product_id: "proposal_ai", status: "unavailable", observed_at: null, effective_until: null }], effective_until: null })));
  renderCabinet();
  await screen.findByRole("article");
  fireEvent.click(screen.getByRole("button", { name: ru.Billing.open }));
  await screen.findByRole("button", { name: ru.Billing.close });
  fireEvent.click(screen.getByRole("button", { name: ru.Billing.close }));
  await waitFor(() => expect(paid).toHaveBeenCalledTimes(2));
  expect(screen.queryByText(a.confirmed)).not.toBeInTheDocument();
  expect(fetcher.mock.calls.some(([url]) => String(url).includes("advance"))).toBe(false);
});

it("does not read paid state for an unverified email", () => {
  renderCabinet(undefined, false);
  expect(paid).not.toHaveBeenCalled();
});

it("does not adopt a silently replaced session on an already mounted account", async () => {
  renderCabinet();
  await screen.findByText(a.confirmed);
  window.localStorage.setItem(sessionStorageKey, "another-session");
  refresh();
  expect(screen.queryByText(a.confirmed)).not.toBeInTheDocument();
  expect(paid).toHaveBeenCalledTimes(1);
});
