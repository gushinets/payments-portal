import { describe, expect, it } from "vitest";
import {
  evaluatePasswordPolicy,
  PASSWORD_SPECIAL_CHARACTERS
} from "@/shared/password-policy";

describe("shared new-password policy", () => {
  it.each([
    ["Aa1!aaaaaaa", ["length"]],
    ["aa1!aaaaaaaa", ["uppercase"]],
    ["AA1!AAAAAAAA", ["lowercase"]],
    ["Aaa!aaaaaaaa", ["digit"]],
    ["Aaa1aaaaaaaa", ["special"]]
  ] as const)(
    "reports unmet requirements for %s",
    (password, unmetRequirements) => {
      expect(evaluatePasswordPolicy(password)).toEqual({
        valid: false,
        unmetRequirements
      });
    }
  );

  it("accepts the exact length boundaries by Unicode code point", () => {
    expect(evaluatePasswordPolicy("Aa1!aaaaaaa💡").valid).toBe(true);
    expect(evaluatePasswordPolicy(`Aa1!${"a".repeat(124)}`).valid).toBe(true);
    expect(
      evaluatePasswordPolicy(`Aa1!${"a".repeat(125)}`).unmetRequirements
    ).toContain("length");
  });

  it("accepts every allowed special character without mutating additions", () => {
    for (const specialCharacter of PASSWORD_SPECIAL_CHARACTERS) {
      expect(
        evaluatePasswordPolicy(`ValidPass123${specialCharacter} Юникод ";`).valid
      ).toBe(true);
    }
  });
});
