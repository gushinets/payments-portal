"use client";

import { useEffect, useState } from "react";
import { LogIn, UserRound } from "lucide-react";
import { useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";
import {
  ApiError,
  decodeAuthSessionResponse,
  getJson,
  sessionChangedEvent,
  sessionStorageKey,
  submitAuth,
  type AuthUser
} from "@/shared/api/auth";
import { AuthForm, AuthFormSubmitValues, AuthMode } from "./AuthForm";
import { EmailVerificationPending } from "./EmailVerificationPending";
import { authErrorMessageKey } from "./auth-errors";

const telegramLoginUrl = process.env.NEXT_PUBLIC_TELEGRAM_LOGIN_URL ?? "";

export function HeaderAccount({ languageTag }: { languageTag: string }) {
  const t = useTranslations("Auth");
  const [sessionUser, setSessionUser] = useState<AuthUser | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [initialAuthMode, setInitialAuthMode] = useState<AuthMode>("login");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [verificationPending, setVerificationPending] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function loadHeaderSession() {
      const token = window.localStorage.getItem(sessionStorageKey);
      if (!token) {
        setSessionUser(null);
        setLoaded(true);
        return;
      }

      try {
        const payload = await getJson(
          "/api/auth/session",
          token,
          decodeAuthSessionResponse
        );
        if (
          !cancelled &&
          window.localStorage.getItem(sessionStorageKey) === token &&
          payload.authenticated
        ) {
          setSessionUser(payload.user);
          setLoaded(true);
        }
      } catch (requestError) {
        if (
          requestError instanceof ApiError &&
          requestError.status === 401 &&
          window.localStorage.getItem(sessionStorageKey) === token
        ) {
          window.localStorage.removeItem(sessionStorageKey);
          window.dispatchEvent(new Event(sessionChangedEvent));
          setSessionUser(null);
          setLoaded(true);
        }
        // Keep the existing token during transient network failures.
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
    setVerificationPending(false);
    setModalOpen(true);
  }

  async function authenticate(values: AuthFormSubmitValues) {
    setError("");
    setNotice("");

    setLoading(true);
    try {
      const payload = await submitAuth(values, { languageTag });
      window.localStorage.setItem(sessionStorageKey, payload.token);
      window.dispatchEvent(new Event(sessionChangedEvent));
      setSessionUser(payload.user);
      if (payload.user.email_verified) {
        setModalOpen(false);
      } else {
        setVerificationPending(true);
      }
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
      ) : sessionUser ? (
        <Link className="btn-secondary nav-account" href="/account">
          <UserRound size={15} aria-hidden="true" />
          <span className="nav-account-email">{sessionUser.email}</span>
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
            {verificationPending ? (
              <EmailVerificationPending languageTag={languageTag} />
            ) : (
              <AuthForm
                title={t("dialogTitle")}
                badgeIcon={<UserRound size={12} aria-hidden="true" />}
                initialMode={initialAuthMode}
                modeOrder={["login", "register"]}
                notice={notice}
                error={error}
                loading={loading}
                telegramLoginUrl={telegramLoginUrl}
                onModeChange={() => {
                  setNotice("");
                  setError("");
                }}
                onPasswordResetClick={() => setModalOpen(false)}
                onBeforeSubmit={() => {
                  setError("");
                  setNotice("");
                }}
                onValidationError={setError}
                onSubmit={authenticate}
              />
            )}
          </div>
        </>
      ) : null}
    </>
  );
}
