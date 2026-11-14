import { expect, it } from "vitest";

import ruMessages from "@/messages/ru.json";
import { inventedSubscriptionState } from "../helpers/subscription-state";

it("subscription-state guard permits an empty catalog but rejects invented access facts", () => {
  expect(ruMessages.CatalogPreview.empty).not.toMatch(inventedSubscriptionState);
  for (const unsupported of ["Нет подписки", "Нет активных подписок", "Нет доступа", "Подписка отсутствует", "Доступа нет", "No subscription", "No access"]) {
    expect(unsupported).toMatch(inventedSubscriptionState);
  }
});
