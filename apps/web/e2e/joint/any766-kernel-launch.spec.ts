import { expect, test } from "@playwright/test";
import { launch } from "./any766-joint";

test("real cabinet launches the same Portal owner through PKCE and clears the callback fragment", async ({ page }, info) => {
  test.setTimeout(120_000);
  await launch(page, info);
  await expect(page.locator("#brief-decoder-brief-text")).toBeVisible();
  await page.reload();
  await expect(page.locator("#brief-decoder-brief-text")).toBeVisible();
  expect(page.url()).not.toContain("#");
});
