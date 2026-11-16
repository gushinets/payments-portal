import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { BackendAuthorization } from "@/features/account/BackendAuthorization";
import { PaidReadStatus } from "@/features/billing/use-paid-read";
import { PaidProductAccess } from "@/features/billing/PaidProductAccess";
import type { usePaidAccess } from "@/features/billing/use-paid-access";
import { kernelWebBaseUrl } from "@/shared/config/kernel-web";
import { parseBackendCallbacks, parseBackendAuthorizationQuery } from "@/shared/config/backend-authorization";
import { sessionChangedEvent, sessionStorageKey } from "@/shared/api/auth";
import ru from "@/messages/ru.json";
import { renderWithIntl } from "../setup/render-with-intl";
import { paidState } from "../fixtures/paid-access";

const fetcher = vi.fn<typeof fetch>();
const navigate = vi.fn();
const challenge = "c".repeat(43);
const state = "s".repeat(43);
const code = "k".repeat(43);
function renderAuthorization() {
  return renderWithIntl(<BackendAuthorization callbacks={[{ consumerId: "platform-kernel", callbackUrl: "https://kernel.invalid/tools/portal-session/callback" }]} navigate={navigate} />, { locale: "ru", messages: ru });
}
beforeEach(() => {
  window.history.replaceState(null, "", `/ru/backend/authorize?consumer_id=platform-kernel&state=${state}&code_challenge=${challenge}&code_challenge_method=S256`);
  window.localStorage.setItem(sessionStorageKey, "synthetic-portal-bearer");
  vi.stubEnv("NEXT_PUBLIC_KERNEL_WEB_BASE_URL", "https://kernel.invalid/tools");
  fetcher.mockReset().mockResolvedValue(Response.json({ code, expires_at: "2099-01-01T00:00:00Z" }));
  navigate.mockReset();
  vi.stubGlobal("fetch", fetcher);
});
afterEach(() => { cleanup(); window.localStorage.clear(); vi.unstubAllEnvs(); vi.unstubAllGlobals(); });

it("uses the fixed callback with code/state only in the fragment", async () => {
  renderAuthorization();
  fireEvent.click(screen.getByRole("button", { name: ru.BackendSession.continue }));
  await waitFor(() => expect(navigate).toHaveBeenCalledOnce());
  const target = new URL(navigate.mock.calls[0][0]);
  expect(target.origin + target.pathname).toBe("https://kernel.invalid/tools/portal-session/callback");
  expect(target.search).toBe("");
  expect(new URLSearchParams(target.hash.slice(1)).get("code")).toBe(code);
  expect(new URLSearchParams(target.hash.slice(1)).get("state")).toBe(state);
  expect(target.href).not.toContain("synthetic-portal-bearer");
  const [url, init] = fetcher.mock.calls[0];
  expect(String(url)).toMatch(/\/api\/backend-session-codes$/);
  expect(init?.headers).toMatchObject({ Authorization: "Bearer synthetic-portal-bearer" });
  expect(JSON.parse(String(init?.body))).toEqual({ consumer_id: "platform-kernel", code_challenge: challenge, code_challenge_method: "S256" });
});

it.each(["", `state=${state}&state=${state}&code_challenge=${challenge}&code_challenge_method=S256`, `state=${state}&code_challenge=${challenge}&code_challenge_method=plain`])("refuses an invalid authorization query %s", (query) => {
  window.history.replaceState(null, "", `/ru/backend/authorize?consumer_id=platform-kernel&${query}`);
  renderAuthorization();
  fireEvent.click(screen.getByRole("button", { name: ru.BackendSession.continue }));
  expect(screen.getByRole("alert").textContent).toBe(ru.BackendSession.failed);
  expect(fetcher).not.toHaveBeenCalled();
  expect(navigate).not.toHaveBeenCalled();
});

it("ignores a code returned after an account change", async () => {
  let resolve!: (response: Response) => void;
  fetcher.mockReturnValue(new Promise<Response>((done) => { resolve = done; }));
  renderAuthorization();
  fireEvent.click(screen.getByRole("button", { name: ru.BackendSession.continue }));
  act(() => {
    window.localStorage.setItem(sessionStorageKey, "another-portal-bearer");
    window.dispatchEvent(new Event(sessionChangedEvent));
  });
  await act(async () => { resolve(Response.json({ code, expires_at: "2099-01-01T00:00:00Z" })); });
  expect(navigate).not.toHaveBeenCalled();
});

it("allows a new one-use code after a lost response", async () => {
  fetcher.mockRejectedValueOnce(new TypeError("lost response"));
  renderAuthorization();
  fireEvent.click(screen.getByRole("button", { name: ru.BackendSession.continue }));
  await screen.findByRole("alert");
  fireEvent.click(screen.getByRole("button", { name: ru.BackendSession.continue }));
  await waitFor(() => expect(navigate).toHaveBeenCalledOnce());
  expect(fetcher).toHaveBeenCalledTimes(2);
});

it("offers product launch only for a current grant", () => {
  const data = paidState();
  const paid: ReturnType<typeof usePaidAccess> = { state: { status: PaidReadStatus.Ready, data, expiresAt: null }, refresh: vi.fn() };
  const view = renderWithIntl(<PaidProductAccess productId="proposal_ai" paid={paid} />, { locale: "ru", messages: ru });
  const link = screen.getByRole("link", { name: ru.Account.products.paid.openProduct });
  expect(link.getAttribute("href")).toBe("https://kernel.invalid/tools/portal-session/launch?return_to=%2Fproducts%2Fproposal_ai");
  view.unmount();
  renderWithIntl(<PaidProductAccess productId="proposal_ai" paid={{ ...paid, state: { status: PaidReadStatus.Ready, expiresAt: null, data: { ...data, grants: [] } } }} />, { locale: "ru", messages: ru });
  expect(screen.queryByRole("link", { name: ru.Account.products.paid.openProduct })).toBeNull();
});

it("keeps paid access visible when the Kernel launch host is unset", () => {
  vi.stubEnv("NEXT_PUBLIC_KERNEL_WEB_BASE_URL", "");
  const paid: ReturnType<typeof usePaidAccess> = {
    state: { status: PaidReadStatus.Ready, data: paidState(), expiresAt: null }, refresh: vi.fn(),
  };
  renderWithIntl(<PaidProductAccess productId="proposal_ai" paid={paid} />, { locale: "ru", messages: ru });
  expect(screen.getByText(ru.Account.products.paid.confirmed)).toBeTruthy();
  expect(screen.getByText(ru.Account.products.paid.launchUnavailable)).toBeTruthy();
  expect(screen.queryByRole("link", { name: ru.Account.products.paid.openProduct })).toBeNull();
});

it("rejects unsafe web-host configuration and duplicate PKCE inputs", () => {
  expect(kernelWebBaseUrl("https://user:secret@kernel.invalid")).toBeNull();
  expect(kernelWebBaseUrl("http://kernel.invalid")).toBeNull();
  expect(kernelWebBaseUrl("http://localhost:3001/tools")).toBe("http://localhost:3001/tools");
  expect(parseBackendAuthorizationQuery(new URLSearchParams(`state=${state}&code_challenge=${challenge}&code_challenge=${challenge}&code_challenge_method=S256`))).toBeNull();
});

it.each(["synthetic-summary", "unknown"])("selects only the configured callback for %s", async (consumerId) => {
  window.history.replaceState(null, "", `/ru/backend/authorize?consumer_id=${consumerId}&state=${state}&code_challenge=${challenge}&code_challenge_method=S256`);
  renderWithIntl(<BackendAuthorization callbacks={[{ consumerId: "synthetic-summary", callbackUrl: "https://summary.invalid/callback" }]} navigate={navigate} />, { locale: "ru", messages: ru });
  fireEvent.click(screen.getByRole("button", { name: ru.BackendSession.continue }));
  if (consumerId === "unknown") {
    expect(fetcher).not.toHaveBeenCalled();
    expect(navigate).not.toHaveBeenCalled();
  } else {
    await waitFor(() => expect(navigate).toHaveBeenCalledOnce());
    expect(new URL(navigate.mock.calls[0][0]).origin).toBe("https://summary.invalid");
    expect(JSON.parse(String(fetcher.mock.calls[0][1]?.body)).consumer_id).toBe(consumerId);
  }
});

it("rejects caller callback tampering before issuing a code", () => {
  window.history.replaceState(null, "", `/ru/backend/authorize?consumer_id=platform-kernel&state=${state}&code_challenge=${challenge}&code_challenge_method=S256&callback=https://evil.invalid`);
  renderAuthorization();
  fireEvent.click(screen.getByRole("button", { name: ru.BackendSession.continue }));
  expect(fetcher).not.toHaveBeenCalled();
  expect(navigate).not.toHaveBeenCalled();
});

it("accepts registered public callbacks and rejects private server configuration", () => {
  expect(parseBackendCallbacks(JSON.stringify([{ consumer_id: "synthetic-summary", callback_url: "https://summary.invalid/callback" }]))).toEqual([{ consumerId: "synthetic-summary", callbackUrl: "https://summary.invalid/callback" }]);
  expect(() => parseBackendCallbacks(JSON.stringify([{ consumer_id: "synthetic-summary", callback_url: "https://summary.invalid/callback", backend_to_portal_current_secret: "must-stay-server-side" }]))).toThrow(/^backend_configuration_invalid$/);
  expect(() => parseBackendCallbacks('[{"consumer_id":"bad","callback_url":"https://user:secret@evil.invalid"}]')).toThrow();
  expect(() => parseBackendCallbacks('[{"consumer_id":"bad","callback_url":"http://evil.invalid"}]')).toThrow();
});
