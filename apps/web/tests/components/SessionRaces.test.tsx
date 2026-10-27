import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, renderHook, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AccountClient } from "@/features/account";
import { EmailVerificationClient } from "@/features/email-verification";
import { EmailVerificationPending } from "@/shared/ui/EmailVerificationPending";
import { HeaderAccount } from "@/shared/ui/HeaderAccount";
import { sessionChangedEvent, sessionStorageKey } from "@/shared/api/auth";
import { useSessionOperation } from "@/shared/session/use-session-operation";
import ruMessages from "@/messages/ru.json";
import { renderWithIntl } from "../setup/render-with-intl";

const fetchMock = vi.fn<typeof fetch>();
const user = { tenant_id: "anytoolai", region: "ru", user_id: "11111111-1111-4111-8111-111111111111", email: "new@example.com", email_verified: true };
const json = (payload: unknown, status = 200) => new Response(JSON.stringify(payload), { status, headers: { "Content-Type": "application/json" } });
function deferred() {
  let resolve: (response: Response) => void = () => undefined;
  let reject: (error: Error) => void = () => undefined;
  const promise = new Promise<Response>((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
}
function renderEntry(entry: string) {
  window.history.replaceState(null, "", entry === "verification" ? "/ru/verify-email#token=capability" : "/ru/account");
  return renderWithIntl(entry === "account" ? <AccountClient languageTag="ru" /> : entry === "header" ? <HeaderAccount languageTag="ru" /> : <EmailVerificationClient languageTag="ru" />, {
    locale: "ru", messages: { Auth: ruMessages.Auth, Account: ruMessages.Account, Billing: ruMessages.Billing, Purchase: ruMessages.Purchase, CatalogPreview: ruMessages.CatalogPreview, EmailVerification: ruMessages.EmailVerification }
  });
}
async function login(entry: string, root = document.body, emailAddress = "old@example.com", mode: "login" | "register" = "login") {
  const form = within(root);
  if (entry === "header") fireEvent.click(await form.findByRole("button", { name: "Войти" }));
  if (mode === "register") fireEvent.click(await form.findByRole("button", { name: ruMessages.Auth.modes.register }));
  const email = await form.findByLabelText("Email");
  fireEvent.change(email, { target: { value: emailAddress } });
  fireEvent.change(form.getByLabelText("Пароль", { exact: true }), { target: { value: "Synthetic-password-123!" } });
  if (mode === "register") {
    fireEvent.change(form.getByLabelText("Повторите пароль"), { target: { value: "Synthetic-password-123!" } });
    form.getAllByRole("checkbox").forEach((checkbox) => fireEvent.click(checkbox));
  }
  fireEvent.submit(email.closest("form")!);
  await waitFor(() => expect(fetchMock.mock.calls.some(([url, options]) => String(url).endsWith(`/api/auth/${mode}`) && String(options?.body).includes(emailAddress))).toBe(true));
}
function changeSession(token: string | null, event: "same-tab" | "storage" = "same-tab", key: string | null = sessionStorageKey) {
  if (token) window.localStorage.setItem(sessionStorageKey, token);
  else window.localStorage.removeItem(sessionStorageKey);
  window.dispatchEvent(event === "same-tab" ? new Event(sessionChangedEvent) : new StorageEvent("storage", { key, storageArea: window.localStorage }));
}

describe.each(["account", "header", "verification"])("%s session races", (entry) => {
  beforeEach(() => { window.localStorage.clear(); fetchMock.mockReset(); vi.stubGlobal("fetch", ((input, init) => String(input).endsWith("/api/catalog/products") ? Promise.resolve(json({ products: [] })) : fetchMock(input, init)) satisfies typeof fetch); });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

  it.each(["success", "failure"])("ignores stale login %s after a newer session", async (result) => {
    const pending = deferred();
    fetchMock.mockImplementation(async (url) => String(url).endsWith("/api/auth/login") ? pending.promise : json({ authenticated: true, user }));
    renderEntry(entry);
    await login(entry);
    act(() => changeSession("new-token"));
    expect(await screen.findByText(user.email)).toBeVisible();
    await act(async () => pending.resolve(result === "success" ? json({ status: "authenticated", token: "old-token", user: { ...user, email: "old@example.com" } }) : json({ detail: "invalid" }, 401)));
    expect(window.localStorage.getItem(sessionStorageKey)).toBe("new-token");
    expect(screen.getByText(user.email)).toBeVisible();
    expect(screen.queryByText("old@example.com")).not.toBeInTheDocument();
    expect(document.querySelector(".notice.error")).toBeNull();
  });

  it("does not commit a login after unmount", async () => {
    const pending = deferred(); fetchMock.mockReturnValue(pending.promise);
    const { unmount } = renderEntry(entry);
    await login(entry);
    const listener = vi.fn(); window.addEventListener(sessionChangedEvent, listener);
    unmount();
    try {
      await act(async () => pending.resolve(json({ status: "authenticated", token: "old-token", user })));
      expect(window.localStorage.getItem(sessionStorageKey)).toBeNull(); expect(listener).not.toHaveBeenCalled();
    } finally { window.removeEventListener(sessionChangedEvent, listener); }
  });

  it("invalidates login when the session returns to the original bearer", async () => {
    const pending = deferred();
    fetchMock.mockImplementation(async (url) => String(url).endsWith("/api/auth/login") ? pending.promise : json({ authenticated: true, user }));
    renderEntry(entry); await login(entry);
    act(() => { changeSession("new-token"); changeSession(null); });
    await act(async () => pending.resolve(json({ status: "authenticated", token: "old-token", user })));
    expect(window.localStorage.getItem(sessionStorageKey)).toBeNull();
    expect(screen.queryByText(user.email)).not.toBeInTheDocument();
  });

  it.each(["success", "401", "503", "timeout"])("recovers a bearer changed without an event during a pending %s read", async (result) => {
    const pending = deferred(); window.localStorage.setItem(sessionStorageKey, "old-token");
    fetchMock.mockReturnValueOnce(pending.promise).mockResolvedValue(json({ authenticated: true, user }));
    renderEntry(entry); await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    window.localStorage.setItem(sessionStorageKey, "new-token");
    await act(async () => {
      if (result === "timeout") pending.reject(new DOMException("Request timed out", "AbortError"));
      else pending.resolve(result === "success" ? json({ authenticated: true, user: { ...user, email: "old@example.com" } }) : json({ detail: "unavailable" }, Number(result)));
    });
    expect(await screen.findByText(user.email)).toBeVisible();
    expect(window.localStorage.getItem(sessionStorageKey)).toBe("new-token"); expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it.each(["success", "401", "503", "timeout"])("native storage invalidates an in-flight %s read", async (result) => {
    const pending = deferred(); window.localStorage.setItem(sessionStorageKey, "old-token");
    fetchMock.mockReturnValueOnce(pending.promise).mockResolvedValue(json({ authenticated: true, user }));
    renderEntry(entry); await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    act(() => changeSession("new-token", "storage"));
    expect(await screen.findByText(user.email)).toBeVisible();
    await act(async () => {
      if (result === "timeout") pending.reject(new DOMException("Request timed out", "AbortError"));
      else pending.resolve(result === "success" ? json({ authenticated: true, user: { ...user, email: "old@example.com" } }) : json({ detail: "unavailable" }, Number(result)));
    });
    expect(screen.getByText(user.email)).toBeVisible(); expect(window.localStorage.getItem(sessionStorageKey)).toBe("new-token"); expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("does not remove the bearer for a session 401 after unmount", async () => {
    const pending = deferred(); window.localStorage.setItem(sessionStorageKey, "new-token");
    fetchMock.mockReturnValueOnce(pending.promise);
    const view = renderEntry(entry);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    view.unmount();
    const listener = vi.fn(); window.addEventListener(sessionChangedEvent, listener);
    try {
      await act(async () => pending.resolve(json({ detail: "unauthorized" }, 401)));
      expect(window.localStorage.getItem(sessionStorageKey)).toBe("new-token");
      expect(listener).not.toHaveBeenCalled();
    } finally { window.removeEventListener(sessionChangedEvent, listener); }
  });

  it.each([sessionStorageKey, null])("handles cross-tab login and logout (key: %s)", async (key) => {
    fetchMock.mockResolvedValue(json({ authenticated: true, user })); renderEntry(entry);
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
    act(() => changeSession("new-token", "storage", key));
    expect(await screen.findByText(user.email)).toBeVisible();
    act(() => changeSession(null, "storage", key));
    await waitFor(() => expect(screen.queryByText(user.email)).not.toBeInTheDocument());
    expect(window.localStorage.getItem(sessionStorageKey)).toBeNull(); expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("ignores unrelated storage and an older read of the same bearer", async () => {
    const pending = deferred(); window.localStorage.setItem(sessionStorageKey, "new-token");
    fetchMock.mockReturnValueOnce(pending.promise).mockResolvedValue(json({ authenticated: true, user }));
    renderEntry(entry); await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    act(() => window.dispatchEvent(new StorageEvent("storage", { key: "unrelated", storageArea: window.localStorage })));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    act(() => window.dispatchEvent(new Event(sessionChangedEvent)));
    expect(await screen.findByText(user.email)).toBeVisible();
    await act(async () => pending.resolve(json({ detail: "unauthorized" }, 401)));
    expect(screen.getByText(user.email)).toBeVisible(); expect(window.localStorage.getItem(sessionStorageKey)).toBe("new-token"); expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});

describe.each(["account", "verification"])("%s and header auth ownership", (entry) => {
  beforeEach(() => { window.localStorage.clear(); fetchMock.mockReset(); vi.stubGlobal("fetch", ((input, init) => String(input).endsWith("/api/catalog/products") ? Promise.resolve(json({ products: [] })) : fetchMock(input, init)) satisfies typeof fetch); });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

  const cases = (["page", "header"] as const).flatMap((first) =>
    (["older", "newer"] as const).flatMap((finishesFirst) =>
      (["success", "failure", "registration"] as const)
        .filter((newerResult) => entry === "account" || first === "page" || newerResult !== "registration")
        .flatMap((newerResult) => (newerResult === "success" ? ["success", "failure"] as const : ["success"] as const)
          .map((olderResult) => ({ first, finishesFirst, olderResult, newerResult })))
    )
  );
  it.each(cases)("$first starts first, $finishesFirst finishes first, older $olderResult and newer $newerResult", async ({ first, finishesFirst, olderResult, newerResult }) => {
    window.history.replaceState(null, "", entry === "verification" ? "/ru/verify-email#token=capability" : "/ru/account");
    const older = deferred();
    const newer = deferred();
    fetchMock.mockImplementation(async (url, options) => {
      if (String(url).endsWith("/login") || String(url).endsWith("/register")) {
        return String(options?.body).includes("old@example.com") ? older.promise : newer.promise;
      }
      return json({ authenticated: true, user });
    });
    renderWithIntl(<>
      <header><HeaderAccount languageTag="ru" /></header>
      <main>{entry === "account" ? <AccountClient languageTag="ru" /> : <EmailVerificationClient languageTag="ru" />}</main>
    </>, { locale: "ru", messages: { Auth: ruMessages.Auth, Account: ruMessages.Account, Billing: ruMessages.Billing, Purchase: ruMessages.Purchase, CatalogPreview: ruMessages.CatalogPreview, EmailVerification: ruMessages.EmailVerification } });
    const page = screen.getByRole("main");
    const header = screen.getByRole("banner");
    const firstRoot = first === "page" ? page : header;
    const secondRoot = first === "page" ? header : page;
    await login(first === "page" ? entry : "header", firstRoot);
    await login(first === "page" ? "header" : entry, secondRoot, user.email, newerResult === "registration" ? "register" : "login");
    const listener = vi.fn();
    window.addEventListener(sessionChangedEvent, listener);
    const finishOlder = () => act(async () => older.resolve(olderResult === "failure"
      ? json({ detail: { code: "invalid_credentials" } }, 401)
      : json({ status: "authenticated", token: "old-token", user: { ...user, email: "old@example.com" } })));
    const finishNewer = () => act(async () => newer.resolve(newerResult === "failure"
      ? json({ detail: { code: "invalid_credentials" } }, 401)
      : json({ status: "authenticated", token: "new-token", user })));
    try {
      if (finishesFirst === "older") {
        await finishOlder();
        expect(window.localStorage.getItem(sessionStorageKey)).toBeNull();
        expect(listener).not.toHaveBeenCalled();
        expect(document.querySelector(".notice")).toBeNull();
        expect(secondRoot.querySelector('button[type="submit"]')).toBeDisabled();
        await finishNewer();
      } else {
        await finishNewer();
        await finishOlder();
      }
      expect(window.localStorage.getItem(sessionStorageKey)).toBe(newerResult === "failure" ? null : "new-token");
      expect(listener).toHaveBeenCalledTimes(newerResult === "failure" ? 0 : 1);
      if (newerResult === "failure") {
        expect(secondRoot.querySelector(".notice.error")).toHaveTextContent(ruMessages.Auth.errors.invalidCredentials);
        expect(firstRoot.querySelector(".notice")).toBeNull();
      } else {
        await waitFor(() => expect(within(page).getByText(user.email)).toBeVisible());
        expect(within(header).getByText(user.email)).toBeVisible();
        expect(document.querySelector(".notice.error")).toBeNull();
      }
      expect(screen.queryByText("old@example.com")).not.toBeInTheDocument();
    } finally { window.removeEventListener(sessionChangedEvent, listener); }
  });
});

describe("adjacent mutation lifetime guards", () => {
  beforeEach(() => { window.localStorage.clear(); fetchMock.mockReset(); vi.stubGlobal("fetch", ((input, init) => String(input).endsWith("/api/catalog/products") ? Promise.resolve(json({ products: [] })) : fetchMock(input, init)) satisfies typeof fetch); });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

  it("only auth attempts participate in shared ownership", () => {
    const first = renderHook(useSessionOperation);
    const independent = renderHook(useSessionOperation);
    const second = renderHook(useSessionOperation);
    const olderAuth = first.result.current.beginAuth();
    const ordinary = independent.result.current.begin();
    expect(olderAuth.isCurrent()).toBe(true);
    const newerAuth = second.result.current.beginAuth();
    expect(olderAuth.isCurrent()).toBe(false);
    expect(ordinary.isCurrent()).toBe(true);
    independent.result.current.begin();
    expect(newerAuth.isCurrent()).toBe(true);
    // A superseded auth response can still end its own local spinner.
    expect(olderAuth.isLatest()).toBe(true);
  });

  it.each(["cancel", "unmount"])("does not restore older ownership after the newest auth %s", (action) => {
    const first = renderHook(useSessionOperation);
    const second = renderHook(useSessionOperation);
    const olderAuth = first.result.current.beginAuth();
    const newerAuth = second.result.current.beginAuth();
    if (action === "cancel") second.result.current.cancel();
    else second.unmount();
    expect(newerAuth.isCurrent()).toBe(false);
    expect(olderAuth.isCurrent()).toBe(false);
  });

  it("closing and reopening the modal invalidates the old login and its finally", async () => {
    const first = deferred(); const second = deferred();
    fetchMock.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    renderEntry("header"); await login("header");
    fireEvent.click(screen.getByRole("button", { name: ruMessages.Auth.header.closeDialogAriaLabel }));
    await login("header");
    await act(async () => first.resolve(json({ status: "authenticated", token: "old-token", user })));
    expect(window.localStorage.getItem(sessionStorageKey)).toBeNull();
    expect(screen.getByRole("dialog").querySelector('button[type="submit"]')).toBeDisabled();
    await act(async () => second.resolve(json({ status: "authenticated", token: "new-token", user })));
    expect(window.localStorage.getItem(sessionStorageKey)).toBe("new-token");
  });

  it("verification capability survives cross-tab replacement and stale confirmation", async () => {
    const confirmation = deferred();
    fetchMock.mockImplementation(async (url) => String(url).endsWith("/api/auth/email-verification/confirm") ? confirmation.promise : json({ authenticated: true, user }));
    window.localStorage.setItem(sessionStorageKey, "old-token"); renderEntry("verification");
    const verify = await screen.findByRole("button", { name: ruMessages.EmailVerification.verify.action });
    fireEvent.click(verify);
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/confirm"))).toBe(true));
    act(() => changeSession("new-token", "storage"));
    expect(await screen.findByText(user.email)).toBeVisible();
    await act(async () => confirmation.resolve(json({ status: "verified" })));
    expect(screen.getByRole("button", { name: ruMessages.EmailVerification.verify.action })).toBeEnabled();
    expect(window.location.hash).toBe("");
    fireEvent.click(screen.getByRole("button", { name: ruMessages.EmailVerification.verify.action }));
    await waitFor(() => expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/confirm"))).toHaveLength(2));
    const requests = fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/confirm"));
    expect(requests[1][1]?.body).toBe(JSON.stringify({ token: "capability" }));
    expect(new Headers(requests[1][1]?.headers).get("Authorization")).toBe("Bearer new-token");
  });

  it.each(["resend", "verify"])("%s cannot clear a bearer after unmount", async (operation) => {
    const pending = deferred(); window.localStorage.setItem(sessionStorageKey, "new-token");
    fetchMock.mockImplementation(async (url) => String(url).endsWith("/session") ? json({ authenticated: true, user }) : pending.promise);
    const view = operation === "resend" ? renderWithIntl(<EmailVerificationPending languageTag="ru" />, { locale: "ru", messages: { EmailVerification: ruMessages.EmailVerification } }) : renderEntry("verification");
    const button = await screen.findByRole("button", { name: operation === "resend" ? ruMessages.EmailVerification.pending.resend : ruMessages.EmailVerification.verify.action });
    fireEvent.click(button);
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => !String(url).endsWith("/session"))).toBe(true));
    view.unmount();
    const listener = vi.fn(); window.addEventListener(sessionChangedEvent, listener);
    try {
      await act(async () => pending.resolve(json({ detail: "unauthorized" }, 401)));
      expect(window.localStorage.getItem(sessionStorageKey)).toBe("new-token"); expect(listener).not.toHaveBeenCalled();
    } finally { window.removeEventListener(sessionChangedEvent, listener); }
  });
});

describe.each(["account", "verification"])("%s explicit logout", (entry) => {
  beforeEach(() => { window.localStorage.clear(); fetchMock.mockReset(); vi.stubGlobal("fetch", ((input, init) => String(input).endsWith("/api/catalog/products") ? Promise.resolve(json({ products: [] })) : fetchMock(input, init)) satisfies typeof fetch); });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

  const logoutLabel = entry === "account"
    ? ruMessages.Account.authenticated.signOutAction
    : ruMessages.EmailVerification.verify.switchAccountAction;

  it.each(["success", "500", "503", "network failure", "timeout"])("removes A before pending revoke and stays signed out after unmount (%s)", async (result) => {
    const pending = deferred();
    window.localStorage.setItem(sessionStorageKey, "token-a");
    fetchMock.mockResolvedValueOnce(json({ authenticated: true, user })).mockReturnValueOnce(pending.promise);
    const view = renderEntry(entry);
    const button = await screen.findByRole("button", { name: logoutLabel });
    const listener = vi.fn();
    const removeItem = vi.spyOn(Storage.prototype, "removeItem");
    const consoleError = vi.spyOn(console, "error");
    window.addEventListener(sessionChangedEvent, listener);
    try {
      fireEvent.click(button);
      // Explicit logout commits locally before any backend response or unmount.
      expect(window.localStorage.getItem(sessionStorageKey)).toBeNull();
      expect(screen.getByLabelText("Email")).toBeVisible();
      expect(screen.getByRole("button", { name: "Войти" })).toBeEnabled();
      expect(listener).toHaveBeenCalledTimes(1);
      expect(removeItem).toHaveBeenCalledExactlyOnceWith(sessionStorageKey);
      expect(fetchMock).toHaveBeenCalledTimes(2);
      expect(fetchMock.mock.calls[1][1]?.headers).toMatchObject({ Authorization: "Bearer token-a" });
      view.unmount();
      await act(async () => {
        if (result === "network failure") pending.reject(new TypeError("network unavailable"));
        else if (result === "timeout") pending.reject(new DOMException("Request timed out", "AbortError"));
        else pending.resolve(result === "success" ? json({ status: "logged_out" }) : json({ detail: "unavailable" }, Number(result)));
      });
      expect(window.localStorage.getItem(sessionStorageKey)).toBeNull();
      expect(listener).toHaveBeenCalledTimes(1);
      expect(removeItem).toHaveBeenCalledTimes(1);
      expect(consoleError).not.toHaveBeenCalled();
      expect(fetchMock).toHaveBeenCalledTimes(2);
    } finally { window.removeEventListener(sessionChangedEvent, listener); }
  });

  it("signs out without revoke or a change event when the bearer is already absent", async () => {
    window.localStorage.setItem(sessionStorageKey, "token-a");
    fetchMock.mockResolvedValueOnce(json({ authenticated: true, user }));
    renderEntry(entry);
    const button = await screen.findByRole("button", { name: logoutLabel });
    window.localStorage.removeItem(sessionStorageKey);
    const listener = vi.fn();
    const removeItem = vi.spyOn(Storage.prototype, "removeItem");
    window.addEventListener(sessionChangedEvent, listener);
    try {
      fireEvent.click(button);
      expect(screen.getByLabelText("Email")).toBeVisible();
      expect(window.localStorage.getItem(sessionStorageKey)).toBeNull();
      expect(fetchMock).toHaveBeenCalledTimes(1);
      expect(listener).not.toHaveBeenCalled();
      expect(removeItem).not.toHaveBeenCalled();
    } finally { window.removeEventListener(sessionChangedEvent, listener); }
  });
});
