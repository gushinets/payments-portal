import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PasswordResetConfirmClient } from "@/features/password-reset/PasswordResetConfirmClient";
import { sessionChangedEvent, sessionStorageKey } from "@/shared/api/auth";
import ruMessages from "@/messages/ru.json";
import { renderWithIntl } from "../setup/render-with-intl";

const fetchMock = vi.fn<typeof fetch>();
function renderReset() {
  window.history.replaceState(null, "", "/ru/reset-password#token=reset-capability");
  return renderWithIntl(<PasswordResetConfirmClient />, { locale: "ru", messages: { PasswordReset: ruMessages.PasswordReset } });
}
describe("password reset session ownership", () => {
  beforeEach(() => { window.localStorage.clear(); fetchMock.mockReset(); vi.stubGlobal("fetch", fetchMock); });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
  it.each(["matching", "replacement", "round-trip", "unmounted", "signed-out"])("reset success only removes its original current bearer: %s", async (scenario) => {
    let finish: (value: Response) => void = () => undefined;
    fetchMock.mockReturnValue(new Promise<Response>((resolve) => { finish = resolve; }));
    if (scenario !== "signed-out") window.localStorage.setItem(sessionStorageKey, "original-token");
    const { unmount } = renderReset();
    const fields = screen.getAllByLabelText(/Новый пароль|Повторите пароль/);
    expect(fields).toHaveLength(2);
    for (const field of fields) fireEvent.change(field, { target: { value: "Synthetic-password-123!" } });
    fireEvent.submit(fields[0].closest("form")!);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    if (scenario === "replacement" || scenario === "round-trip") act(() => {
      window.localStorage.setItem(sessionStorageKey, "replacement-token");
      window.dispatchEvent(new StorageEvent("storage", { key: sessionStorageKey, storageArea: window.localStorage }));
      if (scenario === "round-trip") {
        window.localStorage.setItem(sessionStorageKey, "original-token");
        window.dispatchEvent(new Event(sessionChangedEvent));
      }
    });
    if (scenario === "unmounted") unmount();
    const listener = vi.fn(); window.addEventListener(sessionChangedEvent, listener);
    try {
      await act(async () => finish(new Response(JSON.stringify({ status: "password_reset" }), { status: 200 })));
      expect(window.localStorage.getItem(sessionStorageKey)).toBe(scenario === "matching" || scenario === "signed-out" ? null : scenario === "replacement" ? "replacement-token" : "original-token");
      expect(listener).toHaveBeenCalledTimes(scenario === "matching" ? 1 : 0);
      if (scenario !== "unmounted") expect(screen.getByText(ruMessages.PasswordReset.confirm.notices.success)).toBeVisible();
    } finally { window.removeEventListener(sessionChangedEvent, listener); }
  });
  it("keeps the reset error and retry UI", async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ detail: { code: "password_reset_invalid" } }), { status: 400 }));
    window.localStorage.setItem(sessionStorageKey, "original-token"); renderReset();
    const fields = screen.getAllByLabelText(/Новый пароль|Повторите пароль/);
    for (const field of fields) fireEvent.change(field, { target: { value: "Synthetic-password-123!" } });
    fireEvent.submit(fields[0].closest("form")!);
    await waitFor(() => expect(document.querySelector(".notice.error")).toBeVisible());
    expect(window.localStorage.getItem(sessionStorageKey)).toBe("original-token");
    expect(screen.getByRole("button", { name: ruMessages.PasswordReset.confirm.actions.submit })).toBeEnabled();
  });
});
