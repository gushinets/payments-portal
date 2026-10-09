import { act, fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import {
  REGISTRATION_OFFER_CONSENT_TEXT,
  REGISTRATION_PERSONAL_CONSENT_TEXT
} from "@/generated/registration-acceptance";
import ruMessages from "@/messages/ru.json";
import {
  CANONICAL_LEGAL_PATH_BY_SLUG,
  REGISTRATION_ACCEPTANCE_SOURCE_LINKS
} from "@/shared/config/legal-links";
import { AuthForm } from "@/shared/ui";
import { renderWithIntl } from "../setup/render-with-intl";

function renderAuthForm(overrides: Partial<Parameters<typeof AuthForm>[0]> = {}) {
  const props: Parameters<typeof AuthForm>[0] = {
    title: "Аккаунт",
    badgeIcon: <span aria-hidden="true" />,
    loading: false,
    onBeforeSubmit: vi.fn(),
    onValidationError: vi.fn(),
    onSubmit: vi.fn(),
    ...overrides
  };
  renderWithIntl(<AuthForm {...props} />, {
    locale: "ru",
    messages: { Auth: ruMessages.Auth }
  });
  return props;
}

describe("AuthForm characterization", () => {
  it.each(["Email", "Пароль"])("submits login with Enter from %s", async (field) => {
    const user = userEvent.setup();
    const props = renderAuthForm();

    await user.type(screen.getByLabelText("Email"), "user@example.com");
    await user.type(screen.getByLabelText("Пароль"), "password-123");
    await user.click(screen.getByLabelText(field));
    await user.keyboard("{Enter}");

    expect(props.onSubmit).toHaveBeenCalledTimes(1);
    expect(props.onSubmit).toHaveBeenCalledWith({
      mode: "login",
      email: "user@example.com",
      password: "password-123",
      personalConsent: false,
      offerConsent: false
    });
  });

  it("preserves custom email and password validation on Enter", async () => {
    const user = userEvent.setup();
    const props = renderAuthForm();
    await user.type(screen.getByLabelText("Email"), "invalid-email{Enter}");
    expect(props.onValidationError).toHaveBeenLastCalledWith(
      ruMessages.Auth.validation.invalidEmail
    );
    expect(props.onSubmit).not.toHaveBeenCalled();

    await user.clear(screen.getByLabelText("Email"));
    await user.type(screen.getByLabelText("Email"), "user@example.com");
    await user.type(screen.getByLabelText("Пароль"), "short{Enter}");
    expect(props.onValidationError).toHaveBeenLastCalledWith(
      ruMessages.Auth.validation.passwordTooShort
    );
    expect(props.onSubmit).not.toHaveBeenCalled();
  });

  it("requires password confirmation and both consents on Enter", async () => {
    const user = userEvent.setup();
    const props = renderAuthForm({ initialMode: "register" });
    await user.type(screen.getByLabelText("Email"), "new@example.com");
    await user.type(screen.getByLabelText("Пароль"), "Valid-password-123{Enter}");
    expect(props.onValidationError).toHaveBeenLastCalledWith(
      ruMessages.Auth.validation.passwordMismatch
    );
    expect(props.onSubmit).not.toHaveBeenCalled();

    const confirmation = screen.getByLabelText("Повторите пароль");
    await user.type(confirmation, "Valid-password-123{Enter}");
    expect(props.onValidationError).toHaveBeenLastCalledWith(
      ruMessages.Auth.validation.personalConsentRequired
    );
    expect(props.onSubmit).not.toHaveBeenCalled();

    await user.click(screen.getByLabelText(REGISTRATION_PERSONAL_CONSENT_TEXT));
    await user.click(confirmation);
    await user.keyboard("{Enter}");
    expect(props.onValidationError).toHaveBeenLastCalledWith(
      ruMessages.Auth.validation.offerConsentRequired
    );
    expect(props.onSubmit).not.toHaveBeenCalled();

    await user.click(screen.getByLabelText(REGISTRATION_OFFER_CONSENT_TEXT));
    await user.click(confirmation);
    await user.keyboard("{Enter}");
    expect(props.onSubmit).toHaveBeenCalledTimes(1);
    expect(props.onSubmit).toHaveBeenCalledWith({
      mode: "register",
      email: "new@example.com",
      password: "Valid-password-123",
      personalConsent: true,
      offerConsent: true
    });
  });

  it("keeps mode controls, navigation links and keyboard focus separate from submit", async () => {
    const user = userEvent.setup();
    const props = renderAuthForm({ telegramLoginUrl: "https://example.com/telegram" });
    for (const name of ["Вход", "Регистрация"]) {
      expect(screen.getByRole("button", { name })).toHaveAttribute("type", "button");
    }
    expect(screen.getByRole("link", { name: "Забыли пароль?" })).toHaveAttribute("href", "/ru/forgot-password");
    expect(screen.getByRole("link", { name: ruMessages.Auth.actions.telegramSignIn })).toHaveAttribute("href", "https://example.com/telegram");
    await user.click(screen.getByLabelText("Email"));
    await user.tab();
    expect(screen.getByLabelText("Пароль")).toHaveFocus();
    await user.tab({ shift: true });
    expect(screen.getByLabelText("Email")).toHaveFocus();
    await user.click(screen.getByRole("button", { name: "Регистрация" }));
    expect(props.onSubmit).not.toHaveBeenCalled();
  });

  it.each(["click", "Enter"])("ignores repeated submissions while a %s request is pending", async (action) => {
    let finishSubmit: () => void = () => undefined;
    const pendingSubmit = new Promise<void>((resolve) => { finishSubmit = resolve; });
    const user = userEvent.setup();
    const props = renderAuthForm({ onSubmit: vi.fn(() => pendingSubmit) });
    await user.type(screen.getByLabelText("Email"), "user@example.com");
    const password = screen.getByLabelText("Пароль");
    await user.type(password, "password-123");
    const button = screen.getByRole("button", { name: /Войти/ });
    if (action === "click") {
      await user.click(button);
    } else {
      await user.keyboard("{Enter}");
    }
    await user.click(password);
    await user.keyboard("{Enter}{Enter}");
    await user.click(button);
    expect(props.onSubmit).toHaveBeenCalledTimes(1);
    expect(props.onBeforeSubmit).toHaveBeenCalledTimes(1);
    await act(async () => finishSubmit());
  });

  it("ignores a form submission when the consumer is loading", async () => {
    const user = userEvent.setup();
    const props = renderAuthForm({ loading: true });
    await user.type(screen.getByLabelText("Email"), "user@example.com");
    await user.type(screen.getByLabelText("Пароль"), "password-123");
    const form = screen.getByLabelText("Пароль").closest("form");
    if (!form) throw new Error("Expected a native auth form");
    fireEvent.submit(form);
    expect(props.onSubmit).not.toHaveBeenCalled();
    expect(props.onBeforeSubmit).not.toHaveBeenCalled();
  });

  it("submits login without registration consent flags", async () => {
    const user = userEvent.setup();
    const props = renderAuthForm();

    await user.type(screen.getByLabelText("Email"), "user@example.com");
    await user.type(screen.getByLabelText("Пароль"), "password-123");
    await user.click(screen.getByRole("button", { name: /Войти/ }));

    expect(props.onSubmit).toHaveBeenCalledWith({
      mode: "login",
      email: "user@example.com",
      password: "password-123",
      personalConsent: false,
      offerConsent: false
    });
  });

  it("requires personal data and offer acceptance for registration", async () => {
    const user = userEvent.setup();
    const props = renderAuthForm({ initialMode: "register" });

    await user.type(screen.getByLabelText("Email"), "new@example.com");
    await user.type(screen.getByLabelText("Пароль"), "Valid-password-123");
    await user.type(
      screen.getByLabelText("Повторите пароль"),
      "Valid-password-123"
    );
    await user.click(screen.getByRole("button", { name: /Создать аккаунт/ }));

    expect(props.onValidationError).toHaveBeenCalledWith(
      "Нужно дать согласие на обработку персональных данных."
    );
    expect(props.onSubmit).not.toHaveBeenCalled();

    await user.click(
      screen.getByLabelText(/Я даю согласие на обработку персональных данных/)
    );
    await user.click(screen.getByRole("button", { name: /Создать аккаунт/ }));

    expect(props.onValidationError).toHaveBeenLastCalledWith(
      "Нужно принять условия оферты."
    );
    expect(props.onSubmit).not.toHaveBeenCalled();

    await user.click(screen.getByLabelText(/Я принимаю условия/));
    await user.click(screen.getByRole("button", { name: /Создать аккаунт/ }));

    expect(props.onSubmit).toHaveBeenCalledWith({
      mode: "register",
      email: "new@example.com",
      password: "Valid-password-123",
      personalConsent: true,
      offerConsent: true
    });
  });

  it("renders the canonical backend-owned registration statements", () => {
    renderAuthForm({ initialMode: "register" });

    const personalConsent = screen.getByRole("checkbox", {
      name: REGISTRATION_PERSONAL_CONSENT_TEXT
    });
    const offerConsent = screen.getByRole("checkbox", {
      name: REGISTRATION_OFFER_CONSENT_TEXT
    });

    expect(personalConsent).toBeVisible();
    expect(offerConsent).toBeVisible();
    expect(personalConsent).toHaveAttribute("lang", "ru");
    expect(offerConsent).toHaveAttribute("lang", "ru");
    expect(
      personalConsent.closest("label")?.querySelector("span")
    ).toHaveAttribute("lang", "ru");
    expect(
      offerConsent.closest("label")?.querySelector("span")
    ).toHaveAttribute("lang", "ru");
    expect(
      screen.queryByText(/отмены подписки и возврата денежных средств/)
    ).not.toBeInTheDocument();
  });

  it("keeps consent anchors coupled to generated statements and paths", () => {
    const cases: Array<{
      statement: string;
      links: readonly { text: string; href: string }[];
      expectedPaths: readonly string[];
    }> = [
      {
        statement: REGISTRATION_PERSONAL_CONSENT_TEXT,
        links: REGISTRATION_ACCEPTANCE_SOURCE_LINKS.personal,
        expectedPaths: [
          CANONICAL_LEGAL_PATH_BY_SLUG["consent-personal-data"],
          CANONICAL_LEGAL_PATH_BY_SLUG.privacy
        ]
      },
      {
        statement: REGISTRATION_OFFER_CONSENT_TEXT,
        links: REGISTRATION_ACCEPTANCE_SOURCE_LINKS.offer,
        expectedPaths: [CANONICAL_LEGAL_PATH_BY_SLUG.offer]
      }
    ];

    for (const { statement, links, expectedPaths } of cases) {
      for (const { text } of links) {
        expect(statement).toContain(text);
      }
      expect(links.map(({ href }) => href)).toEqual(expectedPaths);
    }
  });
});
