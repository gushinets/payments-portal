"use client";

import CanonicalLink from "next/link";
import { type ReactNode, type Ref, useState } from "react";
import { ArrowRight } from "lucide-react";
import {
  REGISTRATION_OFFER_CONSENT_TEXT,
  REGISTRATION_PERSONAL_CONSENT_TEXT
} from "@/generated/registration-acceptance";
import { Link } from "@/i18n/navigation";
import { CANONICAL_LEGAL_PATH_BY_SLUG } from "@/shared/config/legal-links";

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
  passwordResetHref?: string;
  telegramLoginUrl?: string;
  telegramIcon?: ReactNode;
  feedbackRef?: Ref<HTMLDivElement>;
  onModeChange?: (mode: AuthMode) => void;
  onPasswordResetClick?: () => void;
  onBeforeSubmit: () => void;
  onValidationError: (message: string) => void;
  onSubmit: (values: AuthFormSubmitValues) => Promise<void>;
};

const defaultModeOrder: AuthMode[] = ["login", "register"];

type ConsentTextLink = {
  href: string;
  text: string;
};

const personalConsentLinks: ConsentTextLink[] = [
  {
    href: CANONICAL_LEGAL_PATH_BY_SLUG["consent-personal-data"],
    text: "Согласием на обработку персональных данных"
  },
  {
    href: CANONICAL_LEGAL_PATH_BY_SLUG.privacy,
    text: "Политикой в отношении обработки персональных данных"
  }
];
const offerConsentLinks: ConsentTextLink[] = [
  {
    href: CANONICAL_LEGAL_PATH_BY_SLUG.offer,
    text: "Публичной оферты"
  }
];

function renderConsentText(
  statement: string,
  links: ConsentTextLink[]
): ReactNode[] {
  const content: ReactNode[] = [];
  let cursor = 0;

  for (const link of links) {
    const start = statement.indexOf(link.text, cursor);
    if (start < 0) {
      throw new Error(`Registration consent link text is missing: ${link.text}`);
    }
    content.push(statement.slice(cursor, start));
    content.push(
      <CanonicalLink
        className="inline-link"
        href={link.href}
        target="_blank"
        rel="noopener noreferrer"
        key={link.href}
      >
        {statement.slice(start, start + link.text.length)}
      </CanonicalLink>
    );
    cursor = start + link.text.length;
  }
  content.push(statement.slice(cursor));
  return content;
}

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
  passwordResetHref = "/forgot-password",
  telegramLoginUrl,
  telegramIcon,
  feedbackRef,
  onModeChange,
  onPasswordResetClick,
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

      {mode === "login" ? (
        <Link
          className="auth-form-secondary-link inline-link"
          href={passwordResetHref}
          onClick={onPasswordResetClick}
        >
          Забыли пароль?
        </Link>
      ) : null}

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
              lang="ru"
              aria-label={REGISTRATION_PERSONAL_CONSENT_TEXT}
              checked={personalConsent}
              onChange={(event) => setPersonalConsent(event.target.checked)}
            />
            <span lang="ru">
              {renderConsentText(
                REGISTRATION_PERSONAL_CONSENT_TEXT,
                personalConsentLinks
              )}
            </span>
          </label>

          <label className="checkbox-label">
            <input
              type="checkbox"
              lang="ru"
              aria-label={REGISTRATION_OFFER_CONSENT_TEXT}
              checked={offerConsent}
              onChange={(event) => setOfferConsent(event.target.checked)}
            />
            <span lang="ru">
              {renderConsentText(
                REGISTRATION_OFFER_CONSENT_TEXT,
                offerConsentLinks
              )}
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
