import { describe, expect, it } from "vitest";
import { parseBackendCallbacks } from "@/shared/config/backend-authorization";

describe("public backend callbacks", () => {
  it("accepts only the explicit public projection", () => {
    expect(parseBackendCallbacks(undefined)).toEqual([]);
    expect(parseBackendCallbacks('[{"consumer_id":"platform-kernel","callback_url":"https://kernel.test/portal-session/callback"}]'))
      .toEqual([{ consumerId: "platform-kernel", callbackUrl: "https://kernel.test/portal-session/callback" }]);
  });
  it.each([
    '{"secret":"sensitive-input"',
    '[{"consumer_id":"platform-kernel","callback_url":"sensitive-input"}]',
    '[{"consumer_id":"platform-kernel","callback_url":"https://kernel.test/callback","secret":"sensitive-input"}]',
  ])("rejects malformed or private configuration without echoing it", (raw) => {
    expect(() => parseBackendCallbacks(raw)).toThrow(/^backend_configuration_invalid$/);
  });
});
