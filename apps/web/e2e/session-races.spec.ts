import { expect, test } from "@playwright/test";
import ruMessages from "../src/messages/ru.json";

const key = "anytoolai_session_token_v1";
const user = (email: string) => ({ tenant_id: "anytoolai", region: "ru", user_id: "11111111-1111-4111-8111-111111111111", email, email_verified: true });

for (const first of ["account", "header"] as const) {
  for (const finishesFirst of ["older", "newer"] as const) {
    for (const newerResult of ["success", "failure", "registration"] as const) {
      test(`${first} auth starts first, ${finishesFirst} finishes first, newer ${newerResult} owns the session`, async ({ page }, testInfo) => {
        const deferredResponse = () => {
          let finish: () => void = () => undefined;
          const pending = new Promise<void>((resolve) => { finish = resolve; });
          return { pending, finish };
        };
        const older = deferredResponse();
        const newer = deferredResponse();
        const started: string[] = [];
        await page.addInitScript(() => {
          sessionStorage.setItem("auth-race-events", "0");
          window.addEventListener("anytoolai_session_changed", () => {
            sessionStorage.setItem("auth-race-events", String(Number(sessionStorage.getItem("auth-race-events")) + 1));
          });
        });
        await page.route(/\/api\/auth\/(?:login|register)$/, async (route) => {
          const { email } = route.request().postDataJSON() as { email: string };
          started.push(email);
          await (email === "old@example.com" ? older : newer).pending;
          await route.fulfill(email === "new@example.com" && newerResult === "failure"
            ? { status: 401, json: { detail: { code: "invalid_credentials" } } }
            : { json: { status: "authenticated", token: email, user: user(email) } });
        });
        await page.route("**/api/auth/session", async (route) => {
          const email = route.request().headers().authorization.slice("Bearer ".length);
          await route.fulfill({ json: { authenticated: true, user: user(email) } });
        });
        await page.goto("/ru/account");
        await page.getByRole("button", { name: ruMessages.CookieBanner.acceptAction, exact: true }).click();
        if (first === "header") await page.getByRole("banner").getByRole("button", { name: "Войти", exact: true }).click();
        const account = page.getByRole("main");
        const dialog = page.getByRole("dialog");
        const firstForm = first === "account" ? account : dialog;
        const secondForm = first === "account" ? dialog : account;
        try {
          // For header-first competition, the overlay blocks direct-form pointer
          // input; submit that still-mounted form through native requestSubmit.
          await firstForm.getByLabel("Email").fill("old@example.com", { force: true });
          await firstForm.getByLabel("Пароль", { exact: true }).fill("Synthetic-password-123!", { force: true });
          await firstForm.locator("form").evaluate((form) => { (form as HTMLFormElement).requestSubmit(); });
          await expect.poll(() => started).toEqual(["old@example.com"]);
          if (first === "account") await page.getByRole("banner").getByRole("button", { name: "Войти", exact: true }).click();
          if (newerResult === "registration") {
            await secondForm.getByRole("button", { name: ruMessages.Auth.modes.register, exact: true }).evaluate((button) => (button as HTMLButtonElement).click());
          }
          await secondForm.getByLabel("Email").fill("new@example.com", { force: true });
          await secondForm.getByLabel("Пароль", { exact: true }).fill("Synthetic-password-123!", { force: true });
          if (newerResult === "registration") {
            await secondForm.getByLabel(ruMessages.Auth.fields.passwordConfirmLabel).fill("Synthetic-password-123!", { force: true });
            for (const checkbox of await secondForm.getByRole("checkbox").all()) await checkbox.evaluate((input) => (input as HTMLInputElement).click());
          }
          await secondForm.locator("form").evaluate((form) => { (form as HTMLFormElement).requestSubmit(); });
          await expect.poll(() => started).toEqual(["old@example.com", "new@example.com"]);
          const finishResponse = async (email: string) => {
            const received = page.waitForResponse((response) =>
              /\/api\/auth\/(?:login|register)$/.test(new URL(response.url()).pathname) &&
              (response.request().postDataJSON() as { email: string }).email === email
            );
            (email === "old@example.com" ? older : newer).finish();
            await (await received).finished();
            await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
          };
          if (finishesFirst === "older") {
            await finishResponse("old@example.com");
            expect(await page.evaluate((storageKey) => localStorage.getItem(storageKey), key)).toBeNull();
            expect(await page.evaluate(() => sessionStorage.getItem("auth-race-events"))).toBe("0");
            await expect(page.locator(".notice")).toHaveCount(0);
            await expect(secondForm.locator('button[type="submit"]')).toBeDisabled();
            await finishResponse("new@example.com");
          } else {
            await finishResponse("new@example.com");
            await finishResponse("old@example.com");
          }
          expect(await page.evaluate((storageKey) => localStorage.getItem(storageKey), key)).toBe(newerResult === "failure" ? null : "new@example.com");
          expect(await page.evaluate(() => sessionStorage.getItem("auth-race-events"))).toBe(newerResult === "failure" ? "0" : "1");
          if (newerResult === "failure") {
            await expect(secondForm.locator(".notice.error")).toHaveText(ruMessages.Auth.errors.invalidCredentials);
            await expect(firstForm.locator(".notice")).toHaveCount(0);
          } else {
            await expect(account.getByText("new@example.com", { exact: true })).toBeVisible();
            await expect(page.getByRole("banner").getByText("new@example.com", { exact: true })).toBeVisible();
            await expect(page.locator(".notice.error")).toHaveCount(0);
          }
          await expect(page.getByText("old@example.com", { exact: true })).toHaveCount(0);
          await page.screenshot({ path: testInfo.outputPath(`${first}-${finishesFirst}-${newerResult}-concurrent-auth.png`), fullPage: true });
        } finally { older.finish(); newer.finish(); }
      });
    }
  }
}

for (const oldResult of ["success", "401", "503", "timeout"] as const) {
  test(`native cross-tab login/logout survives pending session ${oldResult}`, async ({ page, context }, testInfo) => {
    let finish: () => void = () => undefined;
    const pending = new Promise<void>((resolve) => { finish = resolve; });
    let oldReads = 0;
    let completedOldReads = 0;
    let newReads = 0;
    await page.route("**/api/auth/session", async (route) => {
      if (route.request().headers().authorization === "Bearer old-token") {
        oldReads += 1;
        await pending;
        if (oldResult === "timeout") await route.abort("timedout");
        else if (oldResult === "success") await route.fulfill({ json: { authenticated: true, user: user("old@example.com") } });
        else await route.fulfill({ status: Number(oldResult), json: { detail: "unavailable" } });
        completedOldReads += 1;
      } else {
        newReads += 1;
        await route.fulfill({ json: { authenticated: true, user: user("new@example.com") } });
      }
    });
    const other = await context.newPage();
    // Both pages share this origin and localStorage. No custom events are sent.
    await other.route("**/api/auth/session", (route) => route.fulfill({ json: { authenticated: true, user: user("other@example.com") } }));
    await other.goto("/ru/pricing");
    await expect(other.getByRole("banner").getByRole("button", { name: "Войти", exact: true })).toBeEnabled();
    await other.evaluate((storageKey) => localStorage.setItem(storageKey, "old-token"), key);
    await page.goto("/ru/account");
    await expect.poll(() => oldReads).toBe(2);
    const account = page.getByRole("main"); const header = page.getByRole("banner");
    try {
      await other.evaluate((storageKey) => localStorage.setItem(storageKey, "new-token"), key);
      await expect(account.getByText("new@example.com", { exact: true })).toBeVisible();
      await expect(header.getByText("new@example.com", { exact: true })).toBeVisible();
      finish(); await expect.poll(() => completedOldReads).toBe(2);
      await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
      expect(await page.evaluate((storageKey) => localStorage.getItem(storageKey), key)).toBe("new-token");
      await expect(page.getByText("old@example.com", { exact: true })).toHaveCount(0);
      await page.screenshot({ path: testInfo.outputPath(`cross-tab-${oldResult}.png`), fullPage: true });
      await other.evaluate(() => localStorage.setItem("unrelated", "value"));
      await other.evaluate((storageKey) => localStorage.removeItem(storageKey), key);
      await expect(account.getByLabel("Email")).toBeVisible();
      await expect(header.getByRole("button", { name: "Войти", exact: true })).toBeEnabled();
      await expect(page.getByText("new@example.com", { exact: true })).toHaveCount(0);
      expect(newReads).toBe(2);
      await other.evaluate((storageKey) => localStorage.setItem(storageKey, "new-token"), key);
      await expect(account.getByText("new@example.com", { exact: true })).toBeVisible();
      await other.evaluate(() => localStorage.clear());
      await expect(account.getByLabel("Email")).toBeVisible();
      await expect(header.getByRole("button", { name: "Войти", exact: true })).toBeEnabled();
      expect(newReads).toBe(4);
    } finally { finish(); await other.close(); }
  });
}

for (const emailVerified of [true, false]) {
  test(`successful header auth remains usable when its session refresh fails (verified: ${emailVerified})`, async ({ page }) => {
    await page.route("**/api/auth/login", (route) => route.fulfill({ json: {
      status: "authenticated", token: "new-token", user: { ...user("new@example.com"), email_verified: emailVerified }
    } }));
    await page.route("**/api/auth/session", (route) => route.fulfill({ status: 503, json: { detail: "unavailable" } }));
    await page.goto("/ru");
    await page.getByRole("button", { name: ruMessages.CookieBanner.acceptAction, exact: true }).click();
    await page.getByRole("banner").getByRole("button", { name: "Войти", exact: true }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("Email").fill("new@example.com");
    await dialog.getByLabel("Пароль", { exact: true }).fill("Synthetic-password-123!");
    const refresh = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/auth/session");
    await dialog.getByLabel("Пароль", { exact: true }).press("Enter");
    await refresh;
    await expect(page.getByRole("banner").getByRole("link", { name: /new@example.com/ })).toBeVisible();
    expect(await page.evaluate((storageKey) => localStorage.getItem(storageKey), key)).toBe("new-token");
    if (emailVerified) await expect(dialog).toHaveCount(0);
    else await expect(dialog.getByRole("heading", { name: ruMessages.EmailVerification.pending.title })).toBeVisible();
  });
}

for (const entry of ["account", "verification"] as const) {
  for (const result of ["success", "503"] as const) {
    for (const nextAction of ["unmount", "login B"] as const) {
      test(`${entry} explicit logout clears A before revoke ${result} and survives ${nextAction}`, async ({ page }, testInfo) => {
        await page.clock.install({ time: new Date("2026-01-01T00:00:00Z") });
        let finish: () => void = () => undefined;
        const pending = new Promise<void>((resolve) => { finish = resolve; });
        let started = false;
        const revokes: string[] = [];
        const pageErrors: string[] = [];
        const consoleErrors: string[] = [];
        page.on("pageerror", (error) => pageErrors.push(error.message));
        page.on("console", (message) => {
          if (message.type() === "error") consoleErrors.push(message.text());
        });
        await page.route("**/api/auth/session", (route) => route.fulfill({ json: {
          authenticated: true,
          user: user(route.request().headers().authorization === "Bearer token-a" ? "old@example.com" : "new@example.com")
        } }));
        await page.route("**/api/auth/logout", async (route) => {
          revokes.push(route.request().headers().authorization);
          started = true;
          await pending;
          await route.fulfill(result === "success"
            ? { json: { status: "logged_out" } }
            : { status: 503, json: { detail: "unavailable" } });
        });
        await page.route("**/api/auth/login", (route) => route.fulfill({ json: {
          status: "authenticated", token: "token-b", user: user("new@example.com")
        } }));
        const confirmations: { bearer: string; body: unknown }[] = [];
        await page.route("**/api/auth/email-verification/confirm", async (route) => {
          confirmations.push({ bearer: route.request().headers().authorization, body: route.request().postDataJSON() });
          await route.fulfill({ json: { status: "verified" } });
        });
        await page.addInitScript((storageKey) => {
          localStorage.setItem(storageKey, "token-a");
          sessionStorage.setItem("explicit-logout-events", "0");
          // A full document navigation would rerun this script and restore A.
          // The unmount case therefore also proves client-side navigation.
          window.addEventListener("anytoolai_session_changed", () => {
            sessionStorage.setItem("explicit-logout-events", String(Number(sessionStorage.getItem("explicit-logout-events")) + 1));
          });
        }, key);
        await page.goto(entry === "account" ? "/ru/account" : "/ru/verify-email#token=capability");
        const main = page.getByRole("main");
        const header = page.getByRole("banner");
        await expect(main.getByText("old@example.com", { exact: true })).toBeVisible();
        await expect(header.getByText("old@example.com", { exact: true })).toBeVisible();
        await page.getByRole("button", { name: ruMessages.CookieBanner.acceptAction, exact: true }).click();
        // Hold application timers while the test controls the pending revoke.
        // Navigation/login on a slow worker must not consume its request timeout.
        await page.clock.pauseAt(new Date("2026-01-01T01:00:00Z"));
        try {
          await main.getByRole("button", { name: entry === "account"
            ? ruMessages.Account.authenticated.signOutAction
            : ruMessages.EmailVerification.verify.switchAccountAction, exact: true }).click();
          await expect.poll(() => started).toBe(true);
          expect(await page.evaluate((storageKey) => localStorage.getItem(storageKey), key)).toBeNull();
          expect(await page.evaluate(() => sessionStorage.getItem("explicit-logout-events"))).toBe("1");
          await expect(main.getByLabel("Email")).toBeVisible();
          await expect(header.getByRole("button", { name: "Войти", exact: true })).toBeEnabled();
          await expect(page.getByText("old@example.com", { exact: true })).toHaveCount(0);
          if (nextAction === "unmount") {
            await header.getByRole("link", { name: "AnyToolAI", exact: true }).click();
            await expect(page).toHaveURL(/\/ru\/?$/);
            await expect(main.getByLabel("Email")).toHaveCount(0);
          } else {
            await main.getByLabel("Email").fill("new@example.com");
            await main.getByLabel("Пароль", { exact: true }).fill("Synthetic-password-123!");
            await main.getByLabel("Пароль", { exact: true }).press("Enter");
            await expect(main.getByText("new@example.com", { exact: true })).toBeVisible();
            await expect(header.getByText("new@example.com", { exact: true })).toBeVisible();
          }
          const completed = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/auth/logout");
          finish();
          await (await completed).finished();
          await page.clock.resume();
          await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
          expect(revokes).toEqual(["Bearer token-a"]);
          expect(await page.evaluate((storageKey) => localStorage.getItem(storageKey), key)).toBe(nextAction === "unmount" ? null : "token-b");
          expect(await page.evaluate(() => sessionStorage.getItem("explicit-logout-events"))).toBe(nextAction === "unmount" ? "1" : "2");
          if (nextAction === "unmount") {
            await expect(header.getByRole("button", { name: "Войти", exact: true })).toBeEnabled();
          } else {
            await expect(main.getByText("new@example.com", { exact: true })).toBeVisible();
            await expect(header.getByText("new@example.com", { exact: true })).toBeVisible();
            if (entry === "verification") {
              expect(new URL(page.url()).hash).toBe("");
              await main.getByRole("button", { name: ruMessages.EmailVerification.verify.action, exact: true }).click();
              await expect(main.getByRole("heading", { name: ruMessages.EmailVerification.verify.successTitle })).toBeVisible();
              expect(confirmations).toEqual([{ bearer: "Bearer token-b", body: { token: "capability" } }]);
            }
          }
          expect(pageErrors).toEqual([]);
          expect(consoleErrors.filter((message) => !message.includes("503 (Service Unavailable)"))).toEqual([]);
          await page.screenshot({ path: testInfo.outputPath(`${entry}-logout-${result}-${nextAction.replace(" ", "-")}.png`), fullPage: true });
        } finally { finish(); }
      });
    }
  }
}
