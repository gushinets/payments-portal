import { describe, expect, it } from "vitest";

import { resolveIntlLocale } from "@/i18n/formatting-locale";

describe("resolveIntlLocale", () => {
  it("resolves route locale identities to canonical formatting locales", () => {
    expect(resolveIntlLocale("pt")).toBe("pt-BR");
    expect(resolveIntlLocale("ru")).toBe("ru");
  });
});
