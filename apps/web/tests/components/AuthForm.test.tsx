import { screen } from "@testing-library/react";
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
    await user.type(screen.getByLabelText("Пароль"), "password-123");
    await user.type(screen.getByLabelText("Повторите пароль"), "password-123");
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
      password: "password-123",
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
