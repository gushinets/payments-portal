import { readFile } from "node:fs/promises";

import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import type { ProductPurchaseStatusResponse } from "../src/generated/api-contracts/types.gen";
import ru from "../src/messages/ru.json";

const sessionKey = "anytoolai_session_token_v1";

// Real Portal HTTP/PostgreSQL + actual Kernel HTTP mock + recorded LBX.
// Interception below only drops/holds real replies; it never fabricates JSON.
test("isolated purchase resumes after lost reply and safely opens the Widget stub", async ({
  page,
  context,
  request
}, info) => {
  test.skip(
    process.env.PURCHASE_FLOW_ACCEPTANCE !== "1",
    "Requires the isolated ANY-709 dev harness"
  );
  const token = process.env.PURCHASE_TEST_SESSION_TOKEN;
  const api = process.env.PLAYWRIGHT_API_BASE_URL;
  const trafficFile = process.env.PURCHASE_TRAFFIC_FILE;
  if (!token || !api || !trafficFile)
    throw new Error("Missing isolated purchase environment");
  const headers = { Authorization: `Bearer ${token}` };
  const scope = `${api}/api/billing/products/proposal_ai/status`;
  const initialResponse = await request.get(scope, { headers });
  expect(initialResponse.status()).toBe(200);
  const initial: ProductPurchaseStatusResponse = await initialResponse.json();

  await page.goto("/ru/products/proposal_ai");
  const journey = page.getByRole("region", { name: ru.Purchase.title });
  await expect(
    journey.getByRole("link", { name: ru.Purchase.signIn })
  ).toBeVisible();
  await page.evaluate(({ key, value }) => localStorage.setItem(key, value), {
    key: sessionKey,
    value: token
  });
  await page.reload();

  if (!initial.purchase_intent_id) {
    await expect(
      journey.getByText("214.08 RUB", { exact: true })
    ).toBeVisible();
    await expect(
      journey.getByRole("button", { name: ru.Purchase.purchase })
    ).toBeDisabled();
    for (const checkbox of await journey.getByRole("checkbox").all())
      await checkbox.check();
    // Let the real backend finish and commit, then lose only the browser reply.
    await page.route(
      "**/api/purchases",
      async (route) => {
        const response = await route.fetch();
        expect(response.status()).toBe(202);
        await route.abort("failed");
      },
      { times: 1 }
    );
    await journey.getByRole("button", { name: ru.Purchase.purchase }).click();
    await expect(
      journey.getByRole("button", { name: ru.Purchase.continue })
    ).toBeEnabled();
  }
  const heldResponse = await request.get(scope, { headers });
  const held: ProductPurchaseStatusResponse = await heldResponse.json();
  expect(held.purchase_intent_id).toBeTruthy();
  await page.reload();
  await expect(
    journey.getByText(
      ru.Purchase.reference.replace("{id}", held.purchase_intent_id!)
    )
  ).toBeVisible();
  if (held.state !== "manage")
    await journey.getByRole("button", { name: ru.Purchase.continue }).click();
  await expect(
    journey.getByRole("button", { name: ru.Purchase.manage })
  ).toBeEnabled();
  await expect(journey.getByText(ru.Purchase.stub)).toHaveCount(0);
  await journey.getByRole("button", { name: ru.Purchase.manage }).click();
  await expect(journey.getByText(ru.Purchase.stub)).toBeVisible();
  await expect(
    journey.getByRole("button", { name: ru.Purchase.close })
  ).toBeFocused();
  const persistent = await page.evaluate(() => ({
    local: Object.entries(localStorage),
    session: Object.entries(sessionStorage),
    url: location.href,
    cookies: document.cookie
  }));
  expect(JSON.stringify(persistent)).not.toContain("SIMULATED:");
  expect(JSON.stringify(persistent)).not.toMatch(/eyJ[a-zA-Z0-9_-]+\./);
  expect(await page.locator("body").innerText()).not.toMatch(
    /SIMULATED:[A-Za-z0-9_-]{32,}/
  );
  const readyA11y = await new AxeBuilder({ page })
    .include(".purchase-journey")
    .analyze();
  expect(readyA11y.violations).toEqual([]);
  await info.attach("purchase-widget", {
    body: await page.screenshot({ fullPage: true }),
    contentType: "image/png"
  });
  await page.keyboard.press("Escape");
  await expect(journey.getByText(ru.Purchase.stub)).toHaveCount(0);
  await expect(
    journey.getByRole("button", { name: ru.Purchase.manage })
  ).toBeFocused();
  await journey.getByRole("button", { name: ru.Purchase.manage }).click();
  await expect(journey.getByText(ru.Purchase.stub)).toBeVisible();

  const otherTab = await context.newPage();
  await otherTab.goto("/ru/products/proposal_ai");
  await otherTab.evaluate((key) => localStorage.removeItem(key), sessionKey);
  await expect(journey.getByText(ru.Purchase.stub)).toHaveCount(0);
  await expect(
    journey.getByRole("link", { name: ru.Purchase.signIn })
  ).toBeVisible();
  await otherTab.close();

  // Hold an actual completed bootstrap reply across a same-tab logout event.
  await page.evaluate(
    ({ key, value }) => {
      localStorage.setItem(key, value);
      window.dispatchEvent(new Event("anytoolai_session_changed"));
    },
    { key: sessionKey, value: token }
  );
  await expect(
    journey.getByRole("button", { name: ru.Purchase.manage })
  ).toBeEnabled();
  let release: () => void = () => undefined;
  const gate = new Promise<void>((done) => {
    release = done;
  });
  let observed: () => void = () => undefined;
  const upstream = new Promise<void>((done) => {
    observed = done;
  });
  await page.route(
    "**/api/billing/widget-bootstrap",
    async (route) => {
      const response = await route.fetch();
      expect(response.status()).toBe(200);
      observed();
      await gate;
      await route.fulfill({ response });
    },
    { times: 1 }
  );
  await journey.getByRole("button", { name: ru.Purchase.manage }).click();
  await upstream;
  await page.evaluate((key) => {
    localStorage.removeItem(key);
    window.dispatchEvent(new Event("anytoolai_session_changed"));
  }, sessionKey);
  release();
  await expect(
    journey.getByRole("link", { name: ru.Purchase.signIn })
  ).toBeVisible();
  await expect(journey.getByText(ru.Purchase.stub)).toHaveCount(0);
  await expect(page).toHaveURL(/\/ru\/products\/proposal_ai$/);

  const lines = (await readFile(trafficFile, "utf8")).trim().split("\n");
  const posts = lines
    .map((line) => JSON.parse(line) as { method: string; path: string })
    .filter((row) => row.method === "POST")
    .map((row) => row.path)
    .sort();
  expect(posts).toEqual(["/agreements", "/subscriptions", "/users"]);
  const violations = await new AxeBuilder({ page })
    .include(".purchase-journey")
    .analyze();
  expect(violations.violations).toEqual([]);
  await info.attach("purchase-journey", {
    body: await page.screenshot({ fullPage: true }),
    contentType: "image/png"
  });
});
