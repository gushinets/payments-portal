import { expect, test, type Locator, type Page } from "@playwright/test";

const sessionStorageKey = "anytoolai_session_token_v1";
type MockUser = {
  tenant_id: string;
  region: string;
  user_id: string;
  email: string;
  email_verified: boolean;
};

function mockUser(email: string, emailVerified = false): MockUser {
  return {
    tenant_id: "anytoolai",
    region: "ru",
    user_id: "11111111-1111-4111-8111-111111111111",
    email,
    email_verified: emailVerified
  };
}

async function completeRegistrationForm(
  scope: Locator,
  email: string,
  password = "Valid-password-123!"
) {
  await scope
    .locator(".auth-mode-row")
    .getByRole("button", { name: /Регистрация|Criar conta|Registrierung/ })
    .click();
  await scope.locator('input[type="email"]').fill(email);
  await scope.locator('input[type="password"]').first().fill(password);
  await scope.locator('input[type="password"]').nth(1).fill(password);
  for (const checkbox of await scope.getByRole("checkbox").all()) {
    await checkbox.check();
  }
}

async function installSession(page: Page, token: string) {
  await page.addInitScript(
    ({ key, value }) => window.localStorage.setItem(key, value),
    { key: sessionStorageKey, value: token }
  );
}

test("registration shows guidance but leaves password-policy authority to the API", async ({
  page
}) => {
  const requests: unknown[] = [];
  await page.route("**/api/auth/register", async (route) => {
    requests.push(route.request().postDataJSON());
    await route.fulfill({
      status: 400,
      contentType: "application/json",
      body: JSON.stringify({
        detail: { code: "password_policy_not_met" }
      })
    });
  });

  await page.goto("/ru/auth-checkout");
  const scope = page.getByRole("main");
  await completeRegistrationForm(scope, "policy@example.com", "Aa1!aaaaaaa");
  await expect(scope.getByText("Требования к паролю")).toBeVisible();
  await expect(
    scope.getByText("Не менее одного символа из !@#$%^&*()-_=+[]{}:,.?", {
      exact: true
    })
  ).toBeVisible();
  await scope.getByRole("button", { name: /Создать аккаунт/ }).click();

  await expect(
    scope.getByText("Пароль не соответствует всем требованиям.")
  ).toBeVisible();
  expect(requests).toEqual([
    {
      email: "policy@example.com",
      password: "Aa1!aaaaaaa",
      personal_consent: true,
      offer_consent: true
    }
  ]);
});

test("registration preserves valid Unicode, spaces, quotes, and semicolons", async ({
  page
}) => {
  const password = 'Valid1! Юникод "quote";';
  const requests: unknown[] = [];
  const user = mockUser("unicode@example.com");

  await page.route("**/api/auth/register", async (route) => {
    requests.push(route.request().postDataJSON());
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ status: "registered", token: "unicode-session", user })
    });
  });
  await page.route("**/api/auth/session", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ authenticated: true, user })
    });
  });

  await page.goto("/ru/auth-checkout");
  const scope = page.getByRole("main");
  await completeRegistrationForm(scope, user.email, password);
  await scope.getByRole("button", { name: /Создать аккаунт/ }).click();

  await expect(
    scope.getByRole("heading", { name: "Подтвердите email", exact: true })
  ).toBeVisible();
  expect(requests).toEqual([
    {
      email: user.email,
      password,
      personal_consent: true,
      offer_consent: true
    }
  ]);
});

test("login keeps existing-credential validation and exposes unverified recovery", async ({
  page
}) => {
  const user = mockUser("login-unverified@example.com");
  const loginRequests: unknown[] = [];
  await page.route("**/api/auth/login", async (route) => {
    loginRequests.push(route.request().postDataJSON());
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ status: "authenticated", token: "login-session", user })
    });
  });
  await page.route("**/api/auth/session", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ authenticated: true, user })
    });
  });

  await page.goto("/ru/auth-checkout");
  const main = page.getByRole("main");
  await main.getByLabel("Email").fill(user.email);
  await main.getByLabel("Пароль").fill("password");
  await main
    .getByRole("button", { name: "Войти", exact: true })
    .click();

  await expect(
    main.getByRole("heading", { name: "Подтвердите email", exact: true })
  ).toBeVisible();
  await expect(
    main.getByRole("button", { name: "Отправить письмо ещё раз" })
  ).toBeVisible();
  expect(loginRequests).toEqual([{ email: user.email, password: "password" }]);
  await expect
    .poll(() => page.evaluate((key) => window.localStorage.getItem(key), sessionStorageKey))
    .toBe("login-session");
});

test("checkout registration and resend use the canonical pt-BR language tag", async ({
  page
}) => {
  const user = mockUser("checkout-pt@example.com");
  const registrationHeaders: Array<string | null> = [];
  const resendRequests: Array<{
    authorization: string | null;
    languageTag: string | null;
    body: unknown;
  }> = [];
  await page.route("**/api/auth/register", async (route) => {
    registrationHeaders.push(await route.request().headerValue("accept-language"));
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ status: "registered", token: "checkout-session", user })
    });
  });
  await page.route("**/api/auth/session", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ authenticated: true, user })
    });
  });
  await page.route("**/api/auth/email-verification/request", async (route) => {
    resendRequests.push({
      authorization: await route.request().headerValue("authorization"),
      languageTag: await route.request().headerValue("accept-language"),
      body: route.request().postDataJSON()
    });
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ status: "accepted" })
    });
  });

  await page.goto("/pt/auth-checkout");
  const scope = page.getByRole("main");
  await completeRegistrationForm(scope, user.email);
  await scope.getByRole("button", { name: "Criar conta" }).last().click();
  await expect(scope.getByText("Verifique seu e-mail")).toBeVisible();
  await scope.getByRole("button", { name: "Enviar o e-mail de verificação novamente" }).click();

  expect(registrationHeaders).toEqual(["pt-BR"]);
  expect(resendRequests).toEqual([
    {
      authorization: "Bearer checkout-session",
      languageTag: "pt-BR",
      body: {}
    }
  ]);
  await expect(
    scope.getByText(/Se outra mensagem puder ser enviada/)
  ).toBeVisible();
});

test("header registration sends its canonical language tag and stays authenticated", async ({
  page
}) => {
  const user = mockUser("header-de@example.com");
  const languageTags: Array<string | null> = [];
  await page.addInitScript(() => {
    window.localStorage.setItem("anytoolai_cookie_notice_v1", "accepted");
  });
  await page.route("**/api/auth/register", async (route) => {
    languageTags.push(await route.request().headerValue("accept-language"));
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ status: "registered", token: "header-session", user })
    });
  });
  await page.route("**/api/auth/session", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ authenticated: true, user })
    });
  });

  await page.goto("/de");
  await page.getByRole("button", { name: "Anmelden" }).click();
  const dialog = page.getByRole("dialog");
  await completeRegistrationForm(dialog, user.email);
  await dialog.getByRole("button", { name: "Konto erstellen" }).click();

  await expect(dialog.getByText("E-Mail bestätigen")).toBeVisible();
  expect(languageTags).toEqual(["de"]);
  await expect
    .poll(() => page.evaluate((key) => window.localStorage.getItem(key), sessionStorageKey))
    .toBe("header-session");
});

test("account reload derives pending state from session and resends without an email address", async ({
  page
}) => {
  const user = mockUser("account-pending@example.com");
  const resendRequests: Array<{
    authorization: string | null;
    languageTag: string | null;
    body: unknown;
  }> = [];
  await installSession(page, "account-session");
  await page.route("**/api/auth/session", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ authenticated: true, user })
    });
  });
  await page.route("**/api/auth/email-verification/request", async (route) => {
    resendRequests.push({
      authorization: await route.request().headerValue("authorization"),
      languageTag: await route.request().headerValue("accept-language"),
      body: route.request().postDataJSON()
    });
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ status: "accepted" })
    });
  });

  await page.goto("/ru/account");
  const main = page.getByRole("main");
  await expect(
    main.getByRole("heading", { name: "Подтвердите email", exact: true })
  ).toBeVisible();
  await main.getByRole("button", { name: "Отправить письмо ещё раз" }).click();
  await expect(
    main.getByText("Если можно отправить новое письмо, оно уже в пути. Проверьте почту.")
  ).toBeVisible();

  expect(resendRequests).toEqual([
    {
      authorization: "Bearer account-session",
      languageTag: "ru",
      body: {}
    }
  ]);
});

test("fragment token stays memory-only, waits for sign-in and verifies without replacing bearer", async ({
  page
}) => {
  const user = mockUser("verify@example.com");
  let verified = false;
  let confirmRequests = 0;
  const sessionFacts: boolean[] = [];
  await page.route("**/api/auth/login", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ status: "authenticated", token: "existing-bearer", user })
    });
  });
  await page.route("**/api/auth/email-verification/confirm", async (route) => {
    confirmRequests += 1;
    expect(await route.request().headerValue("authorization")).toBe(
      "Bearer existing-bearer"
    );
    expect(route.request().postDataJSON()).toEqual({ token: "fragment-token" });
    verified = true;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ status: "verified" })
    });
  });
  await page.route("**/api/auth/session", async (route) => {
    sessionFacts.push(verified);
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        authenticated: true,
        user: { ...user, email_verified: verified }
      })
    });
  });

  await page.goto("/ru/verify-email#token=fragment-token");
  await expect(page).toHaveURL(/\/ru\/verify-email$/);
  expect(confirmRequests).toBe(0);
  await expect(page.getByRole("heading", { name: "Войдите, чтобы подтвердить email" })).toBeVisible();
  const browserPersistence = await page.evaluate(() => ({
    local: Array.from({ length: window.localStorage.length }, (_, index) => [
      window.localStorage.key(index),
      window.localStorage.getItem(window.localStorage.key(index) ?? "")
    ]),
    session: Array.from({ length: window.sessionStorage.length }, (_, index) => [
      window.sessionStorage.key(index),
      window.sessionStorage.getItem(window.sessionStorage.key(index) ?? "")
    ]),
    cookies: document.cookie,
    search: window.location.search
  }));
  expect(JSON.stringify(browserPersistence)).not.toContain("fragment-token");
  expect(browserPersistence.search).toBe("");

  await page.getByLabel("Email").fill(user.email);
  await page.getByLabel("Пароль").fill("password");
  await page
    .getByRole("main")
    .getByRole("button", { name: "Войти", exact: true })
    .click();
  await expect(page.getByRole("button", { name: "Подтвердить email" })).toBeVisible();
  expect(confirmRequests).toBe(0);

  await page.getByRole("button", { name: "Подтвердить email" }).click();
  await expect(page.getByRole("heading", { name: "Email подтверждён" })).toBeVisible();
  expect(confirmRequests).toBe(1);
  expect(
    await page.evaluate((key) => window.localStorage.getItem(key), sessionStorageKey)
  ).toBe("existing-bearer");
  await expect.poll(() => sessionFacts.includes(true)).toBe(true);
});

test("wrong authenticated account can switch without losing the in-memory verification token", async ({
  page
}) => {
  const wrongUser = mockUser("wrong-account@example.com", true);
  const correctUser = mockUser("correct-account@example.com");
  let confirmRequests = 0;
  await installSession(page, "wrong-account-bearer");
  await page.route("**/api/auth/session", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ authenticated: true, user: wrongUser })
    });
  });
  await page.route("**/api/auth/email-verification/confirm", async (route) => {
    confirmRequests += 1;
    expect(route.request().postDataJSON()).toEqual({ token: "correct-account-token" });
    if (confirmRequests === 1) {
      await route.fulfill({
        status: 400,
        contentType: "application/json",
        body: JSON.stringify({
          detail: { code: "invalid_or_expired_verification_token" }
        })
      });
      return;
    }
    expect(await route.request().headerValue("authorization")).toBe(
      "Bearer correct-account-bearer"
    );
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ status: "verified" })
    });
  });
  await page.route("**/api/auth/logout", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ status: "logged_out" })
    });
  });
  await page.route("**/api/auth/login", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "authenticated",
        token: "correct-account-bearer",
        user: correctUser
      })
    });
  });

  await page.goto("/ru/verify-email#token=correct-account-token");
  await expect(page).toHaveURL(/\/ru\/verify-email$/);
  await expect(
    page.getByRole("heading", { name: "Подтвердите email", exact: true })
  ).toBeVisible();
  await expect(
    page.getByRole("main").getByText(wrongUser.email, { exact: true })
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Email уже подтверждён", exact: true })
  ).toHaveCount(0);

  await page.getByRole("button", { name: "Подтвердить email" }).click();
  await expect(
    page.getByText(
      "Ссылка подтверждения недействительна, истекла или уже была использована."
    )
  ).toBeVisible();

  await page.getByRole("button", { name: "Выйти и сменить аккаунт" }).click();
  await expect(
    page.getByRole("heading", { name: "Войдите, чтобы подтвердить email" })
  ).toBeVisible();
  expect(
    await page.evaluate((key) => window.localStorage.getItem(key), sessionStorageKey)
  ).toBeNull();

  await page.getByLabel("Email").fill(correctUser.email);
  await page.getByLabel("Пароль").fill("password");
  await page.getByRole("main").getByRole("button", { name: "Войти", exact: true }).click();
  await expect(page.getByRole("button", { name: "Подтвердить email" })).toBeVisible();
  await page.getByRole("button", { name: "Подтвердить email" }).click();

  await expect(page.getByRole("heading", { name: "Email подтверждён" })).toBeVisible();
  expect(confirmRequests).toBe(2);
});

test("transient session failure retries in place and preserves the verification capability", async ({
  page
}) => {
  const user = mockUser("retry-verification@example.com");
  let sessionRequests = 0;
  const confirmationTokens: string[] = [];
  await installSession(page, "retry-session");
  await page.route("**/api/auth/session", async (route) => {
    sessionRequests += 1;
    if (sessionRequests === 1) {
      await route.fulfill({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({ detail: { code: "internal_server_error" } })
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ authenticated: true, user })
    });
  });
  await page.route("**/api/auth/email-verification/confirm", async (route) => {
    confirmationTokens.push(route.request().postDataJSON().token);
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ status: "verified" })
    });
  });

  await page.goto("/ru/verify-email#token=retry-fragment-token");

  await expect(page).toHaveURL(/\/ru\/verify-email$/);
  await expect(page.getByRole("main").getByRole("alert")).toContainText(
    "Сервис временно недоступен"
  );
  await page
    .getByRole("button", { name: "Повторить загрузку сессии" })
    .click();
  await expect(
    page.getByRole("button", { name: "Подтвердить email" })
  ).toBeVisible();
  await page.getByRole("button", { name: "Подтвердить email" }).click();

  await expect(
    page.getByRole("heading", { name: "Email подтверждён" })
  ).toBeVisible();
  expect(confirmationTokens).toEqual(["retry-fragment-token"]);
});

test("invalid, expired, or used verification capability has one generic error", async ({
  page
}) => {
  const user = mockUser("invalid-token@example.com");
  await installSession(page, "invalid-token-session");
  await page.route("**/api/auth/session", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ authenticated: true, user })
    });
  });
  await page.route("**/api/auth/email-verification/confirm", async (route) => {
    await route.fulfill({
      status: 400,
      contentType: "application/json",
      body: JSON.stringify({
        detail: { code: "invalid_or_expired_verification_token" }
      })
    });
  });

  await page.goto("/ru/verify-email#token=used-or-expired-token");
  await page.getByRole("button", { name: "Подтвердить email" }).click();

  await expect(
    page.getByText(
      "Ссылка подтверждения недействительна, истекла или уже была использована."
    )
  ).toBeVisible();
});

test("logged-out verification without a token requires normal sign-in", async ({
  page
}) => {
  let resendRequests = 0;
  await page.route("**/api/auth/email-verification/request", async (route) => {
    resendRequests += 1;
    await route.abort();
  });

  await page.goto("/ru/verify-email");

  await expect(
    page.getByText(
      "Войдите обычным способом, затем запросите письмо подтверждения в аккаунте."
    )
  ).toBeVisible();
  await expect(page.getByRole("link", { name: "Войти" })).toHaveAttribute(
    "href",
    "/ru/auth-checkout"
  );
  await expect(page.getByRole("button", { name: /Отправить письмо/ })).toHaveCount(0);
  expect(resendRequests).toBe(0);
});
