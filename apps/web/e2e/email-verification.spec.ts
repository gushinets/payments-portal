import { expect, test } from "@playwright/test";

test("registration requires verification, keeps the browser signed out, and resends with route language", async ({
  page
}) => {
  const registrationRequests: Array<{
    body: unknown;
    languageTag: string | null;
  }> = [];
  const resendRequests: Array<{
    body: unknown;
    languageTag: string | null;
  }> = [];

  await page.route("**/api/auth/register", async (route) => {
    registrationRequests.push({
      body: route.request().postDataJSON(),
      languageTag: await route.request().headerValue("accept-language")
    });
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ status: "verification_required" })
    });
  });
  await page.route("**/api/auth/email-verification/request", async (route) => {
    resendRequests.push({
      body: route.request().postDataJSON(),
      languageTag: await route.request().headerValue("accept-language")
    });
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ status: "accepted" })
    });
  });

  await page.goto("/pt/auth-checkout");
  const authShell = page.getByRole("main");
  await authShell.getByRole("button", { name: "Criar conta" }).first().click();
  await authShell.locator('input[type="email"]').fill("verify-user@example.com");
  await authShell
    .locator('input[type="password"]')
    .nth(0)
    .fill("synthetic-password-123");
  await authShell
    .locator('input[type="password"]')
    .nth(1)
    .fill("synthetic-password-123");
  await authShell.locator('input[type="checkbox"]').nth(0).check();
  await authShell.locator('input[type="checkbox"]').nth(1).check();
  await authShell.getByRole("button", { name: /Criar conta/ }).last().click();

  await expect(
    authShell.getByRole("heading", { name: "Confira seu e-mail" })
  ).toBeVisible();
  await expect(authShell.getByText("verify-user@example.com")).toBeVisible();
  expect(
    await page.evaluate(() =>
      window.localStorage.getItem("anytoolai_session_token_v1")
    )
  ).toBeNull();
  expect(registrationRequests).toEqual([
    {
      body: {
        email: "verify-user@example.com",
        password: "synthetic-password-123",
        personal_consent: true,
        offer_consent: true
      },
      languageTag: "pt-BR"
    }
  ]);

  await authShell.getByRole("button", { name: "Enviar outro link" }).click();
  await expect(
    authShell.getByText(
      "Se esta conta ainda precisar de confirmação, enviamos um novo link."
    )
  ).toBeVisible();
  expect(resendRequests).toEqual([
    {
      body: { email: "verify-user@example.com" },
      languageTag: "pt-BR"
    }
  ]);

  await authShell
    .getByRole("button", { name: "Voltar para o login" })
    .click();
  await expect(authShell.getByLabel("Senha", { exact: true })).toBeVisible();
  await expect(authShell.getByLabel("Repita a senha")).toHaveCount(0);
});

test("unverified login enters the same verification recovery state", async ({
  page
}) => {
  await page.route("**/api/auth/login", async (route) => {
    await route.fulfill({
      status: 403,
      contentType: "application/json",
      body: JSON.stringify({
        detail: { code: "email_verification_required" }
      })
    });
  });

  await page.goto("/ru/auth-checkout");
  const authShell = page.getByRole("main");
  await authShell.getByLabel("Email").fill("historical-user@example.com");
  await authShell
    .getByLabel("Пароль", { exact: true })
    .fill("synthetic-password-123");
  await authShell
    .getByRole("button", { name: "Войти", exact: true })
    .last()
    .click();

  await expect(
    authShell.getByRole("heading", { name: "Проверьте почту" })
  ).toBeVisible();
  await expect(authShell.getByText("historical-user@example.com")).toBeVisible();
});

test("verification consumes a fragment token only after explicit password confirmation", async ({
  page
}) => {
  const documentRequests: string[] = [];
  const confirmationRequests: unknown[] = [];
  page.on("request", (request) => {
    if (request.resourceType() === "document") {
      documentRequests.push(request.url());
    }
  });
  await page.route("**/api/auth/email-verification/confirm", async (route) => {
    confirmationRequests.push(route.request().postDataJSON());
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "verified",
        token: "verified-browser-session",
        user: {
          tenant_id: "anytoolai",
          region: "ru",
          user_id: "00000000-0000-0000-0000-000000000001",
          email: "verified-user@example.com"
        }
      })
    });
  });
  await page.route("**/api/auth/session", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        authenticated: true,
        user: {
          tenant_id: "anytoolai",
          region: "ru",
          user_id: "00000000-0000-0000-0000-000000000001",
          email: "verified-user@example.com"
        }
      })
    });
  });

  await page.goto("/ru/verify-email#token=test-only-verification-token");
  await expect(page).toHaveURL(/\/ru\/verify-email$/);
  expect(documentRequests).toHaveLength(1);
  expect(documentRequests[0]).not.toContain("test-only-verification-token");
  await expect(page.locator(".locale-switcher")).toHaveCount(0);
  expect(confirmationRequests).toEqual([]);

  await page.getByLabel("Текущий пароль").fill("synthetic-password-123");
  await page.getByRole("button", { name: "Подтвердить" }).click();

  await expect(
    page.getByRole("heading", { name: "Аккаунт готов" })
  ).toBeVisible();
  expect(confirmationRequests).toEqual([
    {
      token: "test-only-verification-token",
      password: "synthetic-password-123"
    }
  ]);
  expect(
    await page.evaluate(() =>
      window.localStorage.getItem("anytoolai_session_token_v1")
    )
  ).toBe("verified-browser-session");
});

test("an invalid verification token offers generic email-based resend recovery", async ({
  page
}) => {
  const resendRequests: Array<{
    body: unknown;
    languageTag: string | null;
  }> = [];
  await page.route("**/api/auth/email-verification/confirm", async (route) => {
    await route.fulfill({
      status: 400,
      contentType: "application/json",
      body: JSON.stringify({
        detail: { code: "invalid_or_expired_verification_token" }
      })
    });
  });
  await page.route("**/api/auth/email-verification/request", async (route) => {
    resendRequests.push({
      body: route.request().postDataJSON(),
      languageTag: await route.request().headerValue("accept-language")
    });
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ status: "accepted" })
    });
  });

  await page.goto("/de/verify-email#token=expired-verification-token");
  await page.getByLabel("Aktuelles Passwort").fill("synthetic-password-123");
  await page.getByRole("button", { name: "Bestätigen" }).click();

  await expect(
    page.getByRole("heading", { name: "Weiteren Link anfordern" })
  ).toBeVisible();
  await page.getByLabel("E-Mail").fill("retry-user@example.com");
  await page.getByRole("button", { name: "Neuen Link senden" }).click();

  await expect(
    page.getByText(
      "Falls dieses Konto noch bestätigt werden muss, haben wir einen neuen Link gesendet."
    )
  ).toBeVisible();
  expect(resendRequests).toEqual([
    {
      body: { email: "retry-user@example.com" },
      languageTag: "de"
    }
  ]);
});

test("verification resend maps the authentication rate limit", async ({
  page
}) => {
  await page.route("**/api/auth/email-verification/request", async (route) => {
    await route.fulfill({
      status: 429,
      contentType: "application/json",
      body: JSON.stringify({
        detail: { code: "authentication_rate_limited" }
      })
    });
  });

  await page.goto("/ru/verify-email");
  await page.getByLabel("Email").fill("rate-limited@example.com");
  await page.getByRole("button", { name: "Отправить новую ссылку" }).click();

  await expect(
    page.getByText("Слишком много попыток подтверждения. Попробуйте позже.")
  ).toBeVisible();
});
