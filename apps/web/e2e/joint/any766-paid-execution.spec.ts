import { expect, test } from "@playwright/test";
import { accessibility, launch } from "./any766-joint";
import ru from "../../src/messages/ru.json";

test("real paid browser result survives reload and agrees with durable cabinet usage", async ({ page, request }, info) => {
  test.setTimeout(150_000);
  const { portal, identity } = await launch(page, info);
  const usage = async () => {
    const response = await request.get(`${process.env.PLAYWRIGHT_API_BASE_URL}/api/paid-usage`, { headers: { Authorization: `Bearer ${identity.token}` } });
    expect(response.status()).toBe(200);
    const body = await response.json() as { items: { product_id: string; successful_used?: number; reserved?: number; available?: number }[] };
    return body.items.find((item) => item.product_id === "brief_decoder");
  };
  const before = (await usage())?.successful_used ?? 0;
  let starts = 0;
  page.on("request", (request) => { if (request.method() === "POST" && request.url().endsWith("/scenarios/brief_decoder.decode_v1/start")) starts += 1; });
  await page.locator("#brief-decoder-brief-text").fill("Need a website for my bakery by the holidays, modern but traditional.");
  await page.getByRole("button", { name: "Decode brief", exact: true }).click();
  await expect(page.getByRole("button", { name: "Copy", exact: true })).toBeVisible({ timeout: 60_000 });
  await expect.poll(async () => (await usage())?.successful_used).toBe(before + 1);
  expect((await usage())?.reserved).toBe(0);
  await page.reload();
  await expect(page.getByRole("button", { name: "Copy", exact: true })).toBeVisible({ timeout: 30_000 });
  expect(starts).toBe(1);
  await accessibility(page, info, "paid-result");
  await page.goto(`${portal}/ru/account`);
  const card = page.getByRole("article").filter({ has: page.getByRole("heading", { name: "brief_decoder", exact: true }) });
  await expect(card.locator(".paid-usage-values div").filter({ has: page.getByText(ru.Account.products.usage.used, { exact: true }) }).locator("dd")).toHaveText(String(before + 1));
  await accessibility(page, info, "cabinet-usage");
});
