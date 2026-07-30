import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { AuthForm } from "@/shared/ui";

function renderAuthForm(overrides: Partial<Parameters<typeof AuthForm>[0]> = {}) {
  const props: Parameters<typeof AuthForm>[0] = {
    title: "Аккаунт",
    badgeIcon: <span aria-hidden="true" />,
    loading: false,
    personalConsentError: "Нужно согласие на персональные данные.",
    offerConsentError: "Нужно принять оферту.",
    onBeforeSubmit: vi.fn(),
    onValidationError: vi.fn(),
    onSubmit: vi.fn(),
    ...overrides
  };
  render(<AuthForm {...props} />);
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
      "Нужно согласие на персональные данные."
    );
    expect(props.onSubmit).not.toHaveBeenCalled();

    await user.click(
      screen.getByLabelText(/Я даю согласие на обработку персональных данных/)
    );
    await user.click(screen.getByRole("button", { name: /Создать аккаунт/ }));

    expect(props.onValidationError).toHaveBeenLastCalledWith(
      "Нужно принять оферту."
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
});
