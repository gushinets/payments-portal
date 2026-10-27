import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BillingAccount } from "@/features/billing";
import { AccountClient } from "@/features/account";
import type { WidgetBootstrapResponse } from "@/generated/api-contracts/types.gen";
import ruMessages from "@/messages/ru.json";
import { sessionChangedEvent, sessionStorageKey } from "@/shared/api/auth";
import { ApiError } from "@/shared/api/transport";
import { AuthForm, type AuthFormSubmitValues } from "@/shared/ui";
import { renderWithIntl } from "../setup/render-with-intl";

const { bootstrap, mount, dispose } = vi.hoisted(() => ({
  bootstrap: vi.fn(), mount: vi.fn(), dispose: vi.fn()
}));
vi.mock("@/shared/api/billing", () => ({ bootstrapWidget: bootstrap }));
// Only the official SDK boundary is replaced. Production has no mock mode.
vi.mock("@/features/billing/official-widget-sdk", () => ({ mountOfficialWidget: mount }));

function response(): WidgetBootstrapResponse {
  return {
    presentation: "account", credential: "private-jwt", widget_origin: "https://billing.test",
    sdk_url: "https://billing.test/lbxwidget.js", serviceBaseUrl: "https://billing.test/api/rest/v1/client",
    disableCreateSubscription: true, disableEditSubscription: true, disableStopSubscription: true,
    disableAutopayments: true, disablePayments: true, disableInvoiceGeneration: true, request_id: "request-123"
  };
}

const user = { tenant_id: "anytoolai", region: "ru", user_id: "11111111-1111-4111-8111-111111111111", email: "synthetic@example.com", email_verified: true };
const messages = { Billing: ruMessages.Billing, Purchase: ruMessages.Purchase, Account: ruMessages.Account, Auth: ruMessages.Auth, CatalogPreview: ruMessages.CatalogPreview, EmailVerification: ruMessages.EmailVerification };
function renderBilling(verified = true) {
  return renderWithIntl(<BillingAccount key="first" userId={user.user_id} emailVerified={verified} />, { locale: "ru", messages });
}

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
  window.localStorage.setItem(sessionStorageKey, "portal-session");
  bootstrap.mockReset().mockImplementation(async () => response());
  mount.mockReset().mockImplementation(() => dispose);
  dispose.mockReset();
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("ANY-709 Step 2 account Widget", () => {
  it("opens only on explicit action, including an empty account; no token storage", async () => {
    const view = renderBilling();
    expect(bootstrap).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: ruMessages.Billing.open }));
    await waitFor(() => expect(mount).toHaveBeenCalledTimes(1));
    expect(bootstrap).toHaveBeenCalledWith("portal-session", expect.any(String));
    expect(mount.mock.calls[0][1].disableCreateSubscription).toBe(true);
    expect(mount.mock.calls[0][1].disablePayments).toBe(true);
    expect(Object.keys(window.localStorage)).toEqual([sessionStorageKey]);
    expect(window.sessionStorage.length).toBe(0);
    view.unmount();
    expect(dispose).toHaveBeenCalled();
    renderBilling();
    expect(bootstrap).toHaveBeenCalledTimes(1); // Reload requires another explicit open.
  });

  it("keeps billing independent of an unresolved catalog request", async () => {
    const fetcher = vi.fn<typeof fetch>((input) => {
      if (String(input).endsWith("/api/auth/session")) return Promise.resolve(new Response(JSON.stringify({ authenticated: true, user }), { status: 200 }));
      return new Promise<Response>(() => undefined);
    });
    vi.stubGlobal("fetch", fetcher);
    renderWithIntl(<AccountClient languageTag="ru" />, { locale: "ru", messages });
    fireEvent.click(await screen.findByRole("button", { name: ruMessages.Billing.open }));
    await waitFor(() => expect(mount).toHaveBeenCalledTimes(1));
    expect(fetcher.mock.calls.some(([url]) => String(url).includes("/api/catalog/"))).toBe(true);
  });

  it("keeps verification and guest guards", async () => {
    const view = renderBilling(false);
    expect(screen.getByRole("button", { name: ruMessages.Billing.open })).toBeDisabled();
    expect(bootstrap).not.toHaveBeenCalled();
    view.unmount();
    window.localStorage.clear();
    renderBilling();
    fireEvent.click(screen.getByRole("button", { name: ruMessages.Billing.open }));
    expect(await screen.findByRole("alert")).toHaveTextContent(ruMessages.Billing.errors.session);
    expect(bootstrap).not.toHaveBeenCalled();
  });

  it.each(["logout", "user_switch", "unmount"])("ignores a late bootstrap after %s", async (change) => {
    let finish!: (result: WidgetBootstrapResponse) => void;
    bootstrap.mockImplementation(() => new Promise<WidgetBootstrapResponse>((resolve) => { finish = resolve; }));
    const view = renderBilling();
    fireEvent.click(screen.getByRole("button", { name: ruMessages.Billing.open }));
    if (change === "unmount") view.unmount();
    else act(() => {
      if (change === "logout") window.localStorage.removeItem(sessionStorageKey);
      else window.localStorage.setItem(sessionStorageKey, "different-session");
      window.dispatchEvent(new Event(sessionChangedEvent));
    });
    const late = response();
    await act(async () => { finish(late); });
    expect(mount).not.toHaveBeenCalled();
    expect(late.credential).toBe("");
  });

  it("clears a mounted SDK on logout and ignores late SDK failure", async () => {
    renderBilling();
    fireEvent.click(screen.getByRole("button", { name: ruMessages.Billing.open }));
    await waitFor(() => expect(mount).toHaveBeenCalledTimes(1));
    act(() => { window.localStorage.clear(); window.dispatchEvent(new Event(sessionChangedEvent)); });
    expect(dispose).toHaveBeenCalled();
    act(() => mount.mock.calls[0][4]());
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("displays localized SDK failure with request ID and can reopen", async () => {
    mount.mockImplementationOnce(() => { throw new Error("private-sdk-error"); });
    renderBilling();
    fireEvent.click(screen.getByRole("button", { name: ruMessages.Billing.open }));
    expect(await screen.findByRole("alert")).toHaveTextContent(ruMessages.Billing.errors.sdk);
    expect(screen.getByRole("alert")).toHaveTextContent("request-123");
    expect(document.body).not.toHaveTextContent("private-sdk-error");
    fireEvent.click(screen.getByRole("button", { name: ruMessages.Billing.open }));
    await waitFor(() => expect(mount).toHaveBeenCalledTimes(2));
  });

  it.each([
    ["billing_customer_pending", "pending"],
    ["billing_server_auth_failed", "serverAuth"],
    ["billing_source_invalid_response", "response"],
    ["billing_source_rejected", "rejected"],
    ["billing_source_unavailable", "unavailable"],
    ["billing_client_not_ready", "client"]
  ] as const)("shows a distinct safe %s error without raw payloads", async (code, key) => {
    bootstrap.mockRejectedValue(new ApiError(503, { code, request_id: "safe-request", raw: "private-jwt synthetic@example.com" }));
    renderBilling();
    fireEvent.click(screen.getByRole("button", { name: ruMessages.Billing.open }));
    expect(await screen.findByRole("alert")).toHaveTextContent(ruMessages.Billing.errors[key]);
    expect(screen.getByRole("alert")).toHaveTextContent("safe-request");
    expect(document.body).not.toHaveTextContent("private-jwt");
    expect(document.body).not.toHaveTextContent("synthetic@example.com");
  });

  it("collects independently optional FIO without requiring profile repair", () => {
    renderWithIntl(<AuthForm title="Account" initialMode="register" loading={false} badgeIcon={null} onBeforeSubmit={vi.fn()} onValidationError={vi.fn()} onSubmit={vi.fn()} />, { locale: "ru", messages });
    for (const label of [ruMessages.Auth.fields.firstNameLabel, ruMessages.Auth.fields.surnameLabel, ruMessages.Auth.fields.patronymicLabel]) {
      expect(screen.getByLabelText(label)).not.toBeRequired();
      expect(screen.getByLabelText(label)).toHaveAttribute("maxlength", "100");
    }
  });
});

describe("official SDK sandbox boundary", () => {
  it("uses only configured origin in CSP, never embeds JWT in the host, and destroys on close", async () => {
    const actual = await vi.importActual<typeof import("@/features/billing/official-widget-sdk")>("@/features/billing/official-widget-sdk");
    const port = () => ({ close: vi.fn(), postMessage: vi.fn(), onmessage: null });
    vi.stubGlobal("MessageChannel", class { port1 = port(); port2 = port(); });
    const node = document.createElement("div");
    const bootstrap = response();
    const destroy = actual.mountOfficialWidget(node, bootstrap, "Billing", () => true, vi.fn());
    const frame = node.querySelector("iframe")!;
    const host = decodeURIComponent(frame.src.split(",").slice(1).join(","));
    expect(host).toContain("https://billing.test/lbxwidget.js");
    expect(host).toContain("connect-src https://billing.test");
    expect(host).not.toContain("private-jwt");
    expect(host).not.toContain("043.lbxbilling");
    expect(host).not.toContain("connect-src *");
    expect(bootstrap.credential).toBe("");
    destroy();
    expect(node.querySelector("iframe")).toBeNull();
  });
});

it("submits only populated, trimmed FIO from registration", async () => {
  const submit = vi.fn<(values: AuthFormSubmitValues) => Promise<void>>(async () => undefined);
  renderWithIntl(<AuthForm title="Account" initialMode="register" loading={false} badgeIcon={null} onBeforeSubmit={vi.fn()} onValidationError={vi.fn()} onSubmit={submit} />, { locale: "ru", messages });
  fireEvent.change(screen.getByLabelText(ruMessages.Auth.fields.surnameLabel), { target: { value: "  Synthetic  " } });
  fireEvent.change(screen.getByLabelText(ruMessages.Auth.fields.emailLabel), { target: { value: "synthetic@example.com" } });
  fireEvent.change(screen.getByLabelText(ruMessages.Auth.fields.passwordLabel), { target: { value: "Strong-password1!" } });
  fireEvent.change(screen.getByLabelText(ruMessages.Auth.fields.passwordConfirmLabel), { target: { value: "Strong-password1!" } });
  screen.getAllByRole("checkbox").forEach((checkbox) => fireEvent.click(checkbox));
  fireEvent.submit(screen.getByLabelText(ruMessages.Auth.fields.emailLabel).closest("form")!);
  await waitFor(() => expect(submit).toHaveBeenCalledTimes(1));
  expect(submit.mock.calls[0][0]).toMatchObject({ surname: "Synthetic", mode: "register" });
  expect(submit.mock.calls[0][0]).not.toHaveProperty("firstName");
  expect(submit.mock.calls[0][0]).not.toHaveProperty("patronymic");
});
