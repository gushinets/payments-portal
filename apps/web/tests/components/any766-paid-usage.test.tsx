import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { ObservedPaidUsage, PaidUsageResponse } from "@/generated/api-contracts/types.gen";
import { AccountBilling } from "@/features/billing";
import { paidReadRefreshMs } from "@/features/billing/use-paid-read";
import ru from "@/messages/ru.json";
import { sessionChangedEvent, sessionStorageKey } from "@/shared/api/auth";
import { paidState } from "../fixtures/paid-access";
import { purchaseUser, savedPurchase, widgetResponse } from "../fixtures/purchase";
import { renderWithIntl } from "../setup/render-with-intl";

vi.mock("@/features/billing/official-widget-sdk", () => ({ mountOfficialWidget: vi.fn(() => () => {}) }));
const usage = vi.fn();
const a = ru.Account.products.paid;
const u = ru.Account.products.usage;
const purchase = { purchase_intent_id: savedPurchase.purchase_intent_id, product_id: "proposal_ai", state: "linked", created_at: "2026-10-27T12:00:00Z" };
function observed(overrides: Partial<ObservedPaidUsage> = {}): PaidUsageResponse {
  return { access_revision: 1, items: [{
    allowance_id: "synthetic-allowance", product_id: "proposal_ai", metric_key: "proposal_ai.generations",
    unit: "generation", quantity: 7, classification: "current", status: "observed",
    successful_used: 2, reserved: 1, remaining: 5, available: 4, read_at: "2026-11-11T06:00:00Z", ...overrides,
  }] };
}
function renderCabinet(emailVerified = true) {
  return renderWithIntl(<AccountBilling userId={purchaseUser.user_id} emailVerified={emailVerified} />, { locale: "ru", messages: ru });
}
beforeEach(() => {
  window.localStorage.setItem(sessionStorageKey, "synthetic-usage-session");
  usage.mockReset().mockImplementation(async () => Response.json(observed()));
  vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input) => {
    const path = new URL(String(input)).pathname;
    if (path === "/api/paid-usage") return usage();
    if (path === "/api/paid-access") return Response.json(paidState());
    if (path === "/api/purchase-intents") return Response.json({ purchases: [purchase], next_cursor: null });
    if (path === "/api/billing/widget-bootstrap") return Response.json(widgetResponse(true));
    throw new Error("unexpected_request");
  }));
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); window.localStorage.clear(); });

it("shows actual counters, local terms and the backend read time independently of access", async () => {
  renderCabinet();
  const region = within(await screen.findByRole("region", { name: u.current }));
  for (const [label, value] of [[u.used, "2"], [u.reserved, "1"], [u.remaining, "5"], [u.available, "4"]]) {
    expect(region.getByText(label).nextElementSibling).toHaveTextContent(value);
  }
  expect(region.getByText(/11\.11\.2026.*06:00:00.*UTC/)).toBeVisible();
  expect(screen.getByText(a.confirmed)).toBeVisible();
  expect(document.body).not.toHaveTextContent(/сброс|reset/i);
});

it.each(["busy", "exhausted"] as const)("distinguishes %s from the other capacity state", async (mode) => {
  usage.mockResolvedValue(Response.json(observed(mode === "busy"
    ? { successful_used: 2, reserved: 5, remaining: 5, available: 0 }
    : { successful_used: 7, reserved: 0, remaining: 0, available: 0 })));
  renderCabinet();
  expect(await screen.findByText(u[mode])).toBeVisible();
  expect(screen.queryByText(u[mode === "busy" ? "exhausted" : "busy"])).not.toBeInTheDocument();
});

it("shows historical actual usage while access is blocked", async () => {
  usage.mockResolvedValue(Response.json(observed({ classification: "historical" })));
  renderCabinet();
  const history = within(await screen.findByRole("region", { name: u.historical }));
  expect(history.getByText("Приобретённый лимит: 7 generation")).toBeVisible();
  expect(history.getByText(u.used).nextElementSibling).toHaveTextContent("2");
});

it.each(["unobserved", "unavailable", "empty", "outage"])("does not invent counters for %s", async (mode) => {
  const item = observed().items[0];
  if (item.status !== "observed") throw new Error("observed_fixture_required");
  const { successful_used: _used, reserved: _reserved, remaining: _remaining, available: _available, read_at: _read, status: _status, ...terms } = item;
  const body = mode === "empty" ? { access_revision: 1, items: [] }
    : { access_revision: 1, items: [{ ...terms, status: mode }] };
  usage.mockResolvedValue(mode === "outage" ? Response.json({ detail: { code: "paid_usage_unavailable" } }, { status: 503 }) : Response.json(body));
  renderCabinet();
  expect(await screen.findByText(mode === "unobserved" ? u.unobserved : a.usageUnavailable)).toBeVisible();
  expect(screen.queryByText(u.used)).not.toBeInTheDocument();
  expect(screen.getByText(a.confirmed)).toBeVisible();
});

it("keeps access usable while usage is delayed and permits an independent refresh", async () => {
  let finish!: (response: Response) => void;
  usage.mockImplementationOnce(() => new Promise<Response>((resolve) => { finish = resolve; }));
  renderCabinet();
  expect(await screen.findByText(a.confirmed)).toBeVisible();
  expect(screen.getByText(u.loading)).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: a.refresh }));
  expect(usage).toHaveBeenCalledTimes(1);
  await act(async () => finish(Response.json(observed())));
  expect(await screen.findByText(u.used)).toBeVisible();
});

it.each(["logout", "replacement", "silent", "unmount"])("ignores late usage and stops polling after %s", async (change) => {
  let finish!: (response: Response) => void;
  usage.mockImplementationOnce(() => new Promise<Response>((resolve) => { finish = resolve; }));
  const view = renderCabinet();
  await waitFor(() => expect(usage).toHaveBeenCalledTimes(1));
  if (change === "unmount") view.unmount();
  else act(() => {
    if (change === "logout") window.localStorage.clear();
    else window.localStorage.setItem(sessionStorageKey, "another-session");
    if (change !== "silent") window.dispatchEvent(new Event(sessionChangedEvent));
  });
  await act(async () => finish(Response.json(observed())));
  expect(screen.queryByText(u.used)).not.toBeInTheDocument();
  vi.useFakeTimers();
  await act(async () => vi.advanceTimersByTimeAsync(paidReadRefreshMs * 2));
  expect(usage).toHaveBeenCalledTimes(1);
});

it("pauses hidden usage and refreshes on returning to the tab", async () => {
  vi.useFakeTimers();
  renderCabinet();
  await act(async () => vi.advanceTimersByTimeAsync(1));
  const visibility = vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
  act(() => document.dispatchEvent(new Event("visibilitychange")));
  await act(async () => vi.advanceTimersByTimeAsync(paidReadRefreshMs * 2));
  expect(usage).toHaveBeenCalledTimes(1);
  visibility.mockReturnValue("visible");
  await act(async () => document.dispatchEvent(new Event("visibilitychange")));
  expect(usage).toHaveBeenCalledTimes(2);
});

it("does not request usage for an unverified email", async () => {
  renderCabinet(false);
  await act(async () => {});
  expect(usage).not.toHaveBeenCalled();
});
