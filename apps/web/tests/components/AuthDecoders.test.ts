import { describe, expect, it } from "vitest";
import {
  decodeApiErrorEnvelope,
  decodeAuthSessionResponse,
  decodeLoginResponse,
  decodeLogoutResponse,
  decodePasswordResetConfirmResponse,
  decodePasswordResetRequestResponse,
  decodeRegisterResponse
} from "@/shared/api/auth";

const authUser = {
  tenant_id: "anytoolai",
  region: "ru",
  user_id: "11111111-1111-4111-8111-111111111111",
  email: "user@example.com"
};

const invalidStatusCases: Array<[
  (payload: unknown) => unknown,
  Record<string, string>
]> = [
  [decodeLogoutResponse, { status: "accepted" }],
  [decodePasswordResetRequestResponse, { status: "password_reset" }],
  [decodePasswordResetConfirmResponse, { status: "accepted" }]
];

describe("auth API decoders", () => {
  it("decodes register and login responses", () => {
    expect(
      decodeRegisterResponse({
        status: "registered",
        token: "register-token",
        user: authUser
      })
    ).toEqual({
      status: "registered",
      token: "register-token",
      user: authUser
    });
    expect(
      decodeLoginResponse({
        status: "authenticated",
        token: "login-token",
        user: authUser
      })
    ).toEqual({
      status: "authenticated",
      token: "login-token",
      user: authUser
    });
  });

  it.each([
    null,
    { status: "authenticated", token: 123, user: authUser },
    { status: "authenticated", token: "token", user: { ...authUser, email: null } },
    { status: "registered", token: "token", user: authUser }
  ])("rejects malformed login responses", (payload) => {
    expect(() => decodeLoginResponse(payload)).toThrow("invalid_auth_response");
  });

  it("decodes the authenticated session response", () => {
    expect(
      decodeAuthSessionResponse({ authenticated: true, user: authUser })
    ).toEqual({ authenticated: true, user: authUser });
  });

  it.each([
    null,
    { authenticated: false, user: authUser },
    { authenticated: true },
    { authenticated: true, user: { ...authUser, user_id: 123 } }
  ])("rejects malformed session responses", (payload) => {
    expect(() => decodeAuthSessionResponse(payload)).toThrow(
      "invalid_session_response"
    );
  });

  it("decodes logout and password-reset status responses", () => {
    expect(decodeLogoutResponse({ status: "logged_out" })).toEqual({
      status: "logged_out"
    });
    expect(
      decodePasswordResetRequestResponse({ status: "accepted" })
    ).toEqual({ status: "accepted" });
    expect(
      decodePasswordResetConfirmResponse({ status: "password_reset" })
    ).toEqual({ status: "password_reset" });
  });

  it.each(invalidStatusCases)("rejects an unexpected status response", (decoder, payload) => {
    expect(() => decoder(payload)).toThrow();
  });

  it("decodes structured API error envelopes without trusting detail", () => {
    expect(
      decodeApiErrorEnvelope({ detail: { code: "invalid_credentials" } })
    ).toEqual({ detail: { code: "invalid_credentials" } });
    expect(decodeApiErrorEnvelope({ detail: ["validation error"] })).toEqual({
      detail: ["validation error"]
    });
  });

  it.each([null, [], {}, { error: { code: "invalid_credentials" } }])(
    "rejects malformed API error envelopes",
    (payload) => {
      expect(() => decodeApiErrorEnvelope(payload)).toThrow(
        "invalid_api_error_response"
      );
    }
  );
});
