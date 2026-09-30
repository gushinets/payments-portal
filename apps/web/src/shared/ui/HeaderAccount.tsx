"use client";

import { useEffect, useState } from "react";
import { LogIn, UserRound } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import {
  DEFAULT_ROUTE_LOCALE,
  isRouteLocale,
  LANGUAGE_TAG_BY_ROUTE_LOCALE
} from "@/generated/locales";
import { Link } from "@/i18n/navigation";
import {
  ApiContractError,
  ApiError,
  decodeAuthSessionResponse,
  getJson,
  requestEmailVerification,
  sessionChangedEvent,
  sessionStorageKey,
  submitAuth
} from "@/shared/api/auth";
import { AuthForm, AuthFormSubmitValues, AuthMode } from "./AuthForm";
import {
  authErrorMessageKey,
  isEmailVerificationRequiredError
} from "./auth-errors";

const telegramLoginUrl = process.env.NEXT_PUBLIC_TELEGRAM_LOGIN_URL ?? "";

export function HeaderAccount() {
  const t = useTranslations("Auth");
  const locale = useLocale();
  const languageTag = LANGUAGE_TAG_BY_ROUTE_LOCALE[
    isRouteLocale(locale) ? locale : DEFAULT_ROUTE_LOCALE
  ];
  const [email, setEmail] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [initialAuthMode, setInitialAuthMode] = useState<AuthMode>("login");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [verificationRequired, setVerificationRequired] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function loadHeaderSession() {
      const token = window.localStorage.getItem(sessionStorageKey);
      if (!token) {
        setEmail("");
        setLoaded(true);
        return;
      }

      try {
        const payload = await getJson(
          "/api/auth/session",
          token,
          decodeAuthSessionResponse
        );
        if (!cancelled && payload.authenticated) {
          setEmail(payload.user.email);
        }
      } catch (requestError) {
        if (
          requestError instanceof ApiError ||
          requestError instanceof ApiContractError
        ) {
          window.localStorage.removeItem(sessionStorageKey);
          window.dispatchEvent(new Event(sessionChangedEvent));
          setEmail("");
        }
        // Keep the existing token during transient network failures.
      } finally {
        if (!cancelled) {
          setLoaded(true);
        }
      }
    }

    const timerId = window.setTimeout(() => {
      void loadHeaderSession();
    }, 0);
    window.addEventListener(sessionChangedEvent, loadHeaderSession);

    return () => {
      cancelled = true;
      window.clearTimeout(timerId);
      window.removeEventListener(sessionChangedEvent, loadHeaderSession);
    };
  }, []);

  function openAuthModal(nextMode: AuthMode = "login") {
    setInitialAuthMode(nextMode);
    setNotice("");
    setError("");
    setVerificationRequired(false);
    setModalOpen(true);
  }

  async function authenticate(values: AuthFormSubmitValues) {
    setError("");
    setNotice("");

    setLoading(true);
    try {
      const payload = await submitAuth(values, { languageTag });
      if (payload.status === "verification_required") {
        setVerificationRequired(true);
        return;
      }
      window.localStorage.setItem(sessionStorageKey, payload.token);
      window.dispatchEvent(new Event(sessionChangedEvent));
      setEmail(payload.user.email);
      setModalOpen(false);
    } catch (requestError) {
      if (isEmailVerificationRequiredError(requestError)) {
        setVerificationRequired(true);
        return;
      }
      setError(t(authErrorMessageKey(requestError)));
    } finally {
      setLoading(false);
    }
  }

  async function resendVerification(emailAddress: string) {
    setError("");
    setNotice("");
    setLoading(true);
    try {
      await requestEmailVerification({ email: emailAddress }, { languageTag });
      setNotice(t("verification.notices.resent"));
    } catch (requestError) {
      setError(t(authErrorMessageKey(requestError)));
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      {!loaded ? (
        <button className="btn-secondary nav-account" type="button" disabled>
          <UserRound size={15} aria-hidden="true" />
          {t("header.account")}
        </button>
      ) : email ? (
        <Link className="btn-secondary nav-account" href="/account">
          <UserRound size={15} aria-hidden="true" />
          <span className="nav-account-email">{email}</span>
          <small>{t("header.accountArea")}</small>
        </Link>
      ) : (
        <button
          className="btn-primary nav-account"
          type="button"
          onClick={() => openAuthModal("login")}
        >
          <LogIn size={15} aria-hidden="true" />
          {t("header.signIn")}
        </button>
      )}

      {modalOpen ? (
        <>
          <button
            className="auth-modal-overlay"
            type="button"
            aria-label={t("header.closeDialogAriaLabel")}
            onClick={() => setModalOpen(false)}
          />
          <div
            className="form-panel auth-modal-panel auth-header-modal"
            role="dialog"
            aria-modal="true"
            aria-label={t("header.dialogAriaLabel")}
          >
            <AuthForm
              title={t("dialogTitle")}
              badgeIcon={<UserRound size={12} aria-hidden="true" />}
              initialMode={initialAuthMode}
              modeOrder={["login", "register"]}
              notice={notice}
              error={error}
              verificationRequired={verificationRequired}
              loading={loading}
              telegramLoginUrl={telegramLoginUrl}
              onModeChange={() => {
                setNotice("");
                setError("");
                setVerificationRequired(false);
              }}
              onPasswordResetClick={() => setModalOpen(false)}
              onBeforeSubmit={() => {
                setError("");
                setNotice("");
              }}
              onValidationError={setError}
              onResendVerification={resendVerification}
              onVerificationBack={() => {
                setVerificationRequired(false);
                setNotice("");
                setError("");
              }}
              onSubmit={authenticate}
            />
          </div>
        </>
      ) : null}
    </>
  );
}
