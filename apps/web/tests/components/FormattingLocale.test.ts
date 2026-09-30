import { describe, expect, it } from "vitest";

import { resolveIntlLocale } from "@/i18n/formatting-locale";

describe("resolveIntlLocale", () => {
  it("resolves route locale identities to canonical formatting locales", () => {
    expect(resolveIntlLocale("pt")).toBe("pt-BR");
    expect(resolveIntlLocale("ru")).toBe("ru");
  });

  it("uses Brazilian Portuguese Intl semantics for the pt route", () => {
    const formatter = new Intl.NumberFormat(resolveIntlLocale("pt"));

    expect(formatter.resolvedOptions().locale).toBe("pt-BR");
    expect(formatter.formatToParts(1234.5)).toEqual([
      { type: "integer", value: "1" },
      { type: "group", value: "." },
      { type: "integer", value: "234" },
      { type: "decimal", value: "," },
      { type: "fraction", value: "5" }
    ]);
  });
});
