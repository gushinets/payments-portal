import { expect, test } from "@playwright/test";
import { accessibility, launch } from "./any766-joint";

test("own paid draft, manual legacy restore and later mode choices preserve one execution", async ({ page, request }, info) => {
  test.setTimeout(150_000);
  const { kernel, identity } = await launch(page, info, "client_update_writer");
  const usage = async () => {
    const response = await request.get(`${process.env.PLAYWRIGHT_API_BASE_URL}/api/paid-usage`, { headers: { Authorization: `Bearer ${identity.token}` } });
    expect(response.status()).toBe(200);
    const body = await response.json() as { items: { product_id: string; successful_used: number; reserved: number }[] };
    return body.items.find((item) => item.product_id === "client_update_writer")!;
  };
  const before = (await usage()).successful_used ?? 0;
  let starts = 0;
  page.on("request", (request) => { if (request.method() === "POST" && request.url().endsWith("/start")) starts += 1; });
  const notes = "Homepage redesign is done; checkout is in progress.";
  await page.locator("#client-update-writer-progress-notes").fill(notes);
  await page.locator('label[for="client-update-writer-tone-warm"]').click();
  await page.getByRole("button", { name: "Write update", exact: true }).click();
  await expect(page.getByRole("button", { name: "Copy", exact: true })).toBeVisible({ timeout: 60_000 });
  const accepted = await page.evaluate(() => JSON.parse(sessionStorage.getItem("anytoolai.paid_start.v1.client_update_writer")!) as { scenarioSessionId: string });
  await page.reload();
  await expect(page.getByRole("button", { name: "Copy", exact: true })).toBeVisible();
  await expect(page.locator("#client-update-writer-progress-notes")).toHaveValue(notes);
  await expect(page.getByRole("radio", { name: /warm$/ })).toBeChecked();
  await page.evaluate(() => {
    const key = Object.keys(sessionStorage).find((key) => key.startsWith("anytoolai.paid_draft.v1.") && key.endsWith(".client_update_writer.update"))!;
    const draft = JSON.parse(sessionStorage.getItem(key)!) as { run?: unknown };
    delete draft.run; // A retained older browser draft with no exact result binding.
    sessionStorage.setItem(key, JSON.stringify(draft));
  });
  await page.reload();
  await expect(page.getByRole("button", { name: "Restore saved draft", exact: true })).toBeVisible();
  await expect(page.locator("#client-update-writer-progress-notes")).toHaveValue("");
  await accessibility(page, info, "manual-draft-restore");
  await page.getByRole("button", { name: "Restore saved draft", exact: true }).click();
  await expect(page.locator("#client-update-writer-progress-notes")).toHaveValue(notes);
  await page.getByRole("radio", { name: /Reply Draft$/ }).press("Space");
  await page.reload();
  await expect(page.getByRole("radio", { name: /Reply Draft$/ })).toBeChecked();
  await page.goto(`${kernel}/products/client_update_writer?session=${accepted.scenarioSessionId}&scenario=client_update_writer.update_v1`);
  await expect(page.getByRole("button", { name: "Copy", exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("radio", { name: /Update$/ })).toBeChecked();
  expect(starts).toBe(1);
  await expect.poll(async () => (await usage()).successful_used).toBe(before + 1);
  expect((await usage()).reserved).toBe(0);
});
