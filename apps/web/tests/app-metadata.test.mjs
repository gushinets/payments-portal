import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { fileURLToPath } from "node:url";

const layoutPath = fileURLToPath(new URL("../src/app/layout.tsx", import.meta.url));

test("root metadata keeps public RU branding copy", async () => {
  const source = await readFile(layoutPath, "utf8");

  assert.match(source, /title:\s*"AnytoolAI - RU"/);
  assert.match(
    source,
    /description:\s*"RU-версия платформы цифровых сервисов AnytoolAI\."/
  );
  assert.doesNotMatch(source, /MVP/);
  assert.doesNotMatch(source, /подготовки подключения CloudPayments/);
});
