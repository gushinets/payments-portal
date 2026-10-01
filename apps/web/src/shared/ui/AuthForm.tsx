"use client";

import CanonicalLink from "next/link";
import { useTranslations } from "next-intl";
import { type ReactNode, type Ref, useId, useState } from "react";
import { ArrowRight } from "lucide-react";
import {
  REGISTRATION_OFFER_CONSENT_TEXT,
  REGISTRATION_PERSONAL_CONSENT_TEXT
} from "@/generated/registration-acceptance";
import { Link } from "@/i18n/navigation";
import { REGISTRATION_ACCEPTANCE_SOURCE_LINKS } from "@/shared/config/legal-links";
import {
  evaluatePasswordPolicy,
  PASSWORD_REQUIREMENTS,
  PASSWORD_SPECIAL_CHARACTERS
} from "@/shared/password-policy";

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

function renderConsentText(
  statement: string,
  links: readonly ConsentTextLink[]
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
  const t = useTranslations("Auth");
  const [mode, setMode] = useState<AuthMode>(initialMode);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [passwordConfirm, setPasswordConfirm] = useState("");
  const [personalConsent, setPersonalConsent] = useState(false);
  const [offerConsent, setOfferConsent] = useState(false);
  const passwordRequirementsId = useId();
  const passwordPolicy = evaluatePasswordPolicy(password);

  function selectMode(nextMode: AuthMode) {
    setMode(nextMode);
    onModeChange?.(nextMode);
  }

  async function submit() {
    onBeforeSubmit();

    if (!email.includes("@")) {
      onValidationError(t("validation.invalidEmail"));
      return;
    }

    if (mode === "login" && password.length < 8) {
      onValidationError(t("validation.passwordTooShort"));
      return;
    }

    if (mode === "register") {
      if (!passwordPolicy.valid) {
        onValidationError(t("validation.passwordPolicyNotMet"));
        return;
      }

      if (password !== passwordConfirm) {
        onValidationError(t("validation.passwordMismatch"));
        return;
      }

      if (!personalConsent) {
        onValidationError(t("validation.personalConsentRequired"));
        return;
      }

      if (!offerConsent) {
        onValidationError(t("validation.offerConsentRequired"));
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
        {t("form.badge")}
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
            {authMode === "register"
              ? t("modes.register")
              : t("modes.login")}
          </button>
        ))}
      </div>

      <label className="field-label">
        {t("fields.emailLabel")}
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
        {t("fields.passwordLabel")}
        <input
          className="input"
          type="password"
          autoComplete={mode === "register" ? "new-password" : "current-password"}
          placeholder={
            mode === "register"
              ? t("fields.newPasswordPlaceholder")
              : t("fields.passwordPlaceholder")
          }
          aria-describedby={
            mode === "register" ? passwordRequirementsId : undefined
          }
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
          {t("forgotPasswordAction")}
        </Link>
      ) : null}

      {mode === "register" ? (
        <>
          <div
            className="password-requirements"
            id={passwordRequirementsId}
          >
            <p>{t("passwordRequirements.label")}</p>
            <ul>
              {PASSWORD_REQUIREMENTS.map((requirement) => (
                <li
                  className={
                    passwordPolicy.unmetRequirements.includes(requirement)
                      ? undefined
                      : "password-requirement-met"
                  }
                  key={requirement}
                >
                  {!passwordPolicy.unmetRequirements.includes(requirement) ? (
                    <span>✓ </span>
                  ) : null}
                  {requirement === "special"
                    ? t("passwordRequirements.special", {
                        characters: PASSWORD_SPECIAL_CHARACTERS
                      })
                    : t(`passwordRequirements.${requirement}`)}
                </li>
              ))}
            </ul>
          </div>

          <label className="field-label">
            {t("fields.passwordConfirmLabel")}
            <input
              className="input"
              type="password"
              autoComplete="new-password"
              placeholder={t("fields.passwordConfirmPlaceholder")}
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
                REGISTRATION_ACCEPTANCE_SOURCE_LINKS.personal
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
                REGISTRATION_ACCEPTANCE_SOURCE_LINKS.offer
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
        {mode === "register"
          ? t("actions.createAccount")
          : t("actions.signIn")}
        <ArrowRight size={15} aria-hidden="true" />
      </button>

      {telegramLoginUrl ? (
        <a className="btn-secondary telegram-button" href={telegramLoginUrl}>
          {telegramIcon}
          {t("actions.telegramSignIn")}
        </a>
      ) : null}
    </div>
  );
}
