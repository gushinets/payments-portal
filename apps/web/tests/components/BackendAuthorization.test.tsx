import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { BackendAuthorization } from "@/features/account/BackendAuthorization";
import { sessionStorageKey } from "@/shared/api/auth";
import ru from "@/messages/ru.json";
import { renderWithIntl } from "../setup/render-with-intl";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); window.localStorage.clear(); window.history.replaceState({}, "", "/"); });

it("keeps the parent and PKCE request on 429 and allows retry", async () => {
  const query = new URLSearchParams({ consumer_id: "synthetic-summary", state: "s".repeat(43), code_challenge: "c".repeat(43), code_challenge_method: "S256" });
  window.history.replaceState({}, "", `/ru/backend/authorize?${query}`);
  window.localStorage.setItem(sessionStorageKey, "synthetic-parent");
  const fetchMock = vi.fn<typeof fetch>()
    .mockResolvedValueOnce(Response.json({ detail: { code: "backend_session_rate_limited" } }, { status: 429, headers: { "Retry-After": "60" } }))
    .mockResolvedValueOnce(Response.json({ code: "k".repeat(43), expires_at: "2099-01-01T00:00:00Z" }));
  vi.stubGlobal("fetch", fetchMock);
  const navigate = vi.fn();
  renderWithIntl(<BackendAuthorization callbacks={[{ consumerId: "synthetic-summary", callbackUrl: "https://summary.invalid/callback" }]} navigate={navigate} />, { locale: "ru", messages: ru });
  fireEvent.click(screen.getByRole("button", { name: ru.BackendSession.continue }));
  expect(await screen.findByRole("alert")).toHaveTextContent(ru.BackendSession.rateLimited);
  expect(window.localStorage.getItem(sessionStorageKey)).toBe("synthetic-parent");
  expect(window.location.search).toBe(`?${query}`);
  expect(navigate).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: ru.BackendSession.continue }));
  await waitFor(() => expect(navigate).toHaveBeenCalledOnce());
  expect(new URLSearchParams(new URL(navigate.mock.calls[0][0]).hash.slice(1)).get("state")).toBe("s".repeat(43));
  expect(fetchMock.mock.calls[0][1]?.body).toBe(fetchMock.mock.calls[1][1]?.body);
});
