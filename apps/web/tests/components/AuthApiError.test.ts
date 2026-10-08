import { describe, expect, it } from "vitest";
import { ApiError, apiErrorCode } from "@/shared/api/auth";

function apiError(status: number, detail: unknown) {
  return new ApiError(status, detail);
}

describe("API error classification", () => {
  it("keeps status and structured code as language-neutral transport facts", () => {
    const error = apiError(409, { code: "email_already_registered" });

    expect(error.status).toBe(409);
    expect(apiErrorCode(error)).toBe("email_already_registered");
  });

  it.each([
    new Error("known_code"),
    apiError(400, "known_code"),
    apiError(400, null),
    apiError(400, []),
    apiError(400, { code: 123 })
  ])("returns null unless detail.code is structured and string-valued", (error) => {
    expect(apiErrorCode(error)).toBeNull();
  });
});
