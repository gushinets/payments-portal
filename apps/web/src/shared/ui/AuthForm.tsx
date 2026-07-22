"use client";

import Link from "next/link";
import { type ReactNode, type Ref, useState } from "react";
import { ArrowRight } from "lucide-react";

export type AuthMode = "login" | "register";

export type AuthFormSubmitValues = {
  mode: AuthMode;
  email: string;
  password: string;
  personalConsent: boolean;
  offerConsent: boolean;
};

type AuthFormProps = {
  title: string;
  badgeIcon: ReactNode;
  initialMode?: AuthMode;
  modeOrder?: AuthMode[];
  prompt?: ReactNode;
  notice?: string;
  error?: string;
  loading: boolean;
  personalConsentError: string;
  offerConsentError: string;
  includeCancellationLink?: boolean;
  telegramLoginUrl?: string;
  telegramIcon?: ReactNode;
  feedbackRef?: Ref<HTMLDivElement>;
  onModeChange?: (mode: AuthMode) => void;
  onBeforeSubmit: () => void;
  onValidationError: (message: string) => void;
  onSubmit: (values: AuthFormSubmitValues) => Promise<void>;
};

const defaultModeOrder: AuthMode[] = ["login", "register"];

export function AuthForm({
  title,
  badgeIcon,
  initialMode = "login",
  modeOrder = defaultModeOrder,
  prompt,
  notice,
  error,
  loading,
  personalConsentError,
  offerConsentError,
  includeCancellationLink = false,
  telegramLoginUrl,
  telegramIcon,
  feedbackRef,
  onModeChange,
  onBeforeSubmit,
  onValidationError,
  onSubmit
}: AuthFormProps) {
  const [mode, setMode] = useState<AuthMode>(initialMode);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [passwordConfirm, setPasswordConfirm] = useState("");
  const [personalConsent, setPersonalConsent] = useState(false);
  const [offerConsent, setOfferConsent] = useState(false);

  function selectMode(nextMode: AuthMode) {
    setMode(nextMode);
    onModeChange?.(nextMode);
  }

  async function submit() {
    onBeforeSubmit();

    if (!email.includes("@")) {
      onValidationError("Укажите корректный email.");
      return;
    }

    if (password.length < 8) {
      onValidationError("Пароль должен содержать не менее 8 символов.");
      return;
    }

    if (mode === "register") {
      if (password !== passwordConfirm) {
        onValidationError("Пароли не совпадают.");
        return;
      }

      if (!personalConsent) {
        onValidationError(personalConsentError);
        return;
      }

      if (!offerConsent) {
        onValidationError(offerConsentError);
        return;
      }
    }

    await onSubmit({
      mode,
      email,
      password,
      personalConsent,
      offerConsent
    });
    setPassword("");
    setPasswordConfirm("");
  }

  return (
    <div className="form-grid">
      <span className="badge badge-running">
        {badgeIcon}
        Единый аккаунт
      </span>
      <h2>{title}</h2>
      {prompt}
      <div ref={feedbackRef} aria-live="polite">
        {notice ? <div className="notice">{notice}</div> : null}
        {error ? <div className="notice error">{error}</div> : null}
      </div>
      <div className="auth-mode-row">
        {modeOrder.map((authMode) => (
          <button
            className={mode === authMode ? "btn-primary" : "btn-secondary"}
            type="button"
            onClick={() => selectMode(authMode)}
            key={authMode}
          >
            {authMode === "register" ? "Регистрация" : "Вход"}
          </button>
        ))}
      </div>

      <label className="field-label">
        Email
        <input
          className="input"
          type="email"
          autoComplete="email"
          placeholder="user@example.com"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
      </label>

      <label className="field-label">
        Пароль
        <input
          className="input"
          type="password"
          autoComplete={mode === "register" ? "new-password" : "current-password"}
          placeholder="Не менее 8 символов"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
      </label>

      {mode === "register" ? (
        <>
          <label className="field-label">
            Повторите пароль
            <input
              className="input"
              type="password"
              autoComplete="new-password"
              placeholder="Введите пароль ещё раз"
              value={passwordConfirm}
              onChange={(event) => setPasswordConfirm(event.target.value)}
            />
          </label>

          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={personalConsent}
              onChange={(event) => setPersonalConsent(event.target.checked)}
            />
            <span>
              Я даю согласие на обработку персональных данных в соответствии с{" "}
              <Link
                className="inline-link"
                href="/ru/consent-personal-data"
                target="_blank"
                rel="noopener noreferrer"
              >
                Согласием на обработку персональных данных
              </Link>{" "}
              и{" "}
              <Link
                className="inline-link"
                href="/ru/privacy"
                target="_blank"
                rel="noopener noreferrer"
              >
                Политикой в отношении обработки персональных данных
              </Link>
              .
            </span>
          </label>

          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={offerConsent}
              onChange={(event) => setOfferConsent(event.target.checked)}
            />
            <span>
              Я принимаю условия{" "}
              <Link
                className="inline-link"
                href="/ru/offer"
                target="_blank"
                rel="noopener noreferrer"
              >
                Публичной оферты
              </Link>
              {includeCancellationLink ? (
                <>
                  {" "}
                  и ознакомлен(а) с{" "}
                  <Link
                    className="inline-link"
                    href="/ru/cancellation"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Условиями отмены подписки и возврата денежных средств
                  </Link>
                </>
              ) : null}
              .
            </span>
          </label>
        </>
      ) : null}

      <button
        className="btn-primary"
        type="button"
        onClick={() => {
          void submit();
        }}
        disabled={loading}
      >
        {mode === "register" ? "Создать аккаунт" : "Войти"}
        <ArrowRight size={15} aria-hidden="true" />
      </button>

      {telegramLoginUrl ? (
        <a className="btn-secondary telegram-button" href={telegramLoginUrl}>
          {telegramIcon}
          Войти через Telegram
        </a>
      ) : null}
    </div>
  );
}
