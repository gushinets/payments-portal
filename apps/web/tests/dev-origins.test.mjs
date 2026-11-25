import assert from "node:assert/strict";
import { test } from "node:test";

function setDevOrigins(t, value) {
  const previous = process.env.NEXT_ALLOWED_DEV_ORIGINS;
  const apply = (origin) => {
    if (origin === undefined) {
      delete process.env.NEXT_ALLOWED_DEV_ORIGINS;
    } else {
      process.env.NEXT_ALLOWED_DEV_ORIGINS = origin;
    }
  };

  t.after(() => apply(previous));
  apply(value);
}

test("development origins require explicit opt-in for an extra host", async (t) => {
  setDevOrigins(t, undefined);
  const { default: config } = await import("../next.config.mjs?default");
  assert.deepEqual(config.allowedDevOrigins, []);
});

test("development origins still accept explicitly configured LAN hosts", async (t) => {
  setDevOrigins(t, " https://dev.example.test:3000, , 192.0.2.10 ");
  const { default: config } = await import("../next.config.mjs?explicit");
  assert.deepEqual(config.allowedDevOrigins, ["dev.example.test", "192.0.2.10"]);
});
