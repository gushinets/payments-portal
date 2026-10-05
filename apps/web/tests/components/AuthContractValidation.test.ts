import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ApiContractError,
  ApiError,
  apiErrorCode,
  confirmEmailVerification,
  confirmPasswordReset,
  getSession,
  logoutSession,
  requestEmailVerification,
  requestPasswordReset,
  submitAuth
} from "@/shared/api/auth";

const reportApiContractError = vi.hoisted(() => vi.fn());

vi.mock("@/shared/observability/sentry", () => ({
  reportApiContractError
}));

const fetchMock = vi.fn<typeof fetch>();
const validUser = {
  tenant_id: "anytoolai",
  region: "ru",
  user_id: "11111111-1111-4111-8111-111111111111",
  email: "user@example.com",
  email_verified: false
};

function jsonResponse(payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" }
  });
}

describe("generated auth contract validation", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    reportApiContractError.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("accepts a valid register response and maps the adapter request", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        status: "registered",
        token: "register-token",
        user: validUser
      })
    );

    await expect(
      submitAuth(
        {
          mode: "register",
          email: "user@example.com",
          password: "Very-secret-password1!",
          personalConsent: true,
          offerConsent: true
        },
        { languageTag: "ru" }
      )
    ).resolves.toEqual({
      status: "registered",
      token: "register-token",
      user: validUser
    });
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/api/auth/register"),
      expect.objectContaining({
        body: JSON.stringify({
          email: "user@example.com",
          password: "Very-secret-password1!",
          personal_consent: true,
          offer_consent: true
        })
      })
    );
  });

  it("accepts a valid login response", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        status: "authenticated",
        token: "login-token",
        user: validUser
      })
    );

    await expect(
      submitAuth(
        {
          mode: "login",
          email: "user@example.com",
          password: "very-secret-password",
          personalConsent: false,
          offerConsent: false
        },
        { languageTag: "ru" }
      )
    ).resolves.toEqual({
      status: "authenticated",
      token: "login-token",
      user: validUser
    });
  });

  it("accepts a valid session response and preserves email_verified", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ authenticated: true, user: validUser })
    );

    await expect(getSession("session-token")).resolves.toEqual({
      authenticated: true,
      user: validUser
    });
  });

  it("accepts a backend-serialized IDN email in a session response", async () => {
    const backendSerializedIdnEmail = "user@пример.рф";
    const user = { ...validUser, email: backendSerializedIdnEmail };
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ authenticated: true, user })
    );

    await expect(getSession("session-token")).resolves.toEqual({
      authenticated: true,
      user
    });
  });

  it("accepts valid logout, verification, and password-reset responses", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ status: "logged_out" }))
      .mockResolvedValueOnce(jsonResponse({ status: "accepted" }))
      .mockResolvedValueOnce(jsonResponse({ status: "verified" }))
      .mockResolvedValueOnce(jsonResponse({ status: "accepted" }))
      .mockResolvedValueOnce(jsonResponse({ status: "password_reset" }));

    await expect(logoutSession("session-token")).resolves.toEqual({
      status: "logged_out"
    });
    await expect(
      requestEmailVerification("session-token", "ru")
    ).resolves.toEqual({ status: "accepted" });
    await expect(
      confirmEmailVerification(
        "session-token",
        "verification-token-with-at-least-32-characters"
      )
    ).resolves.toEqual({ status: "verified" });
    await expect(
      requestPasswordReset(
        { email: "user@example.com" },
        { languageTag: "ru" }
      )
    ).resolves.toEqual({ status: "accepted" });
    await expect(
      confirmPasswordReset({
        token: "password-reset-token-with-at-least-32-characters",
        password: "Very-secret-password1!"
      })
    ).resolves.toEqual({ status: "password_reset" });
  });

  it("turns malformed successful JSON into ApiContractError and reports safe metadata", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        authenticated: true,
        user: { email: "private@example.com" }
      })
    );

    await expect(getSession("session-token")).rejects.toBeInstanceOf(
      ApiContractError
    );
    expect(reportApiContractError).toHaveBeenCalledWith(
      expect.any(ApiContractError),
      {
        route: "/api/auth/session",
        contract: "SessionResponse"
      }
    );
    expect(JSON.stringify(reportApiContractError.mock.calls[0])).not.toContain(
      "private@example.com"
    );
  });

  it("keeps API error facts without exposing the raw response body", async () => {
    const rawBody = JSON.stringify({
      detail: {
        code: "email_already_registered",
        email: "private@example.com",
        token: "private-token"
      }
    });
    fetchMock.mockResolvedValueOnce(
      new Response(rawBody, {
        status: 409,
        headers: { "Content-Type": "application/json" }
      })
    );

    const error: unknown = await getSession("session-token").catch(
      (caught: unknown) => caught
    );

    expect(error).toBeInstanceOf(ApiError);
    if (!(error instanceof ApiError)) {
      throw new Error("expected_api_error");
    }
    expect(error.status).toBe(409);
    expect(error.detail).toEqual({
      code: "email_already_registered",
      email: "private@example.com",
      token: "private-token"
    });
    expect(apiErrorCode(error)).toBe("email_already_registered");
    expect(error.message).toBe("api_request_failed");
    expect(error.message).not.toContain(rawBody);
    expect(reportApiContractError).not.toHaveBeenCalled();
  });

  it("rejects an invalid user_id UUID", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        authenticated: true,
        user: { ...validUser, user_id: "user-id" }
      })
    );

    await expect(getSession("session-token")).rejects.toBeInstanceOf(
      ApiContractError
    );
  });

  it("keeps ApiContractError stable when reporting fails", async () => {
    reportApiContractError.mockImplementationOnce(() => {
      throw new Error("reporting unavailable");
    });
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ authenticated: true, user: { email: 123 } })
    );

    await expect(getSession("session-token")).rejects.toBeInstanceOf(
      ApiContractError
    );
  });

  it("rejects a response with missing required fields", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        authenticated: true,
        user: {
          tenant_id: validUser.tenant_id,
          region: validUser.region,
          user_id: validUser.user_id,
          email: validUser.email
        }
      })
    );

    await expect(getSession("session-token")).rejects.toBeInstanceOf(
      ApiContractError
    );
  });
});
