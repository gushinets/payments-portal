"use client";

import { useEffect, useRef, useState } from "react";
import { LogIn, UserRound } from "lucide-react";
import { useTranslations } from "next-intl";
import type { SessionUserResponse } from "@/generated/api-contracts/types.gen";
import { Link } from "@/i18n/navigation";
import {
  ApiError,
  getSession,
  sessionChangedEvent,
  sessionStorageKey,
  submitAuth
} from "@/shared/api/auth";
import {
  subscribeToSessionChanges,
  useSessionOperation
} from "@/shared/session/use-session-operation";
import { AuthForm, AuthFormSubmitValues, AuthMode } from "./AuthForm";
import { EmailVerificationPending } from "./EmailVerificationPending";
import { authErrorMessageKey } from "./auth-errors";

const telegramLoginUrl = process.env.NEXT_PUBLIC_TELEGRAM_LOGIN_URL ?? "";

export function HeaderAccount({ languageTag }: { languageTag: string }) {
  const { begin: beginOperation, cancel: cancelOperation } = useSessionOperation();
  const t = useTranslations("Auth");
  const [sessionUser, setSessionUser] =
    useState<SessionUserResponse | null>(null);
  const sessionUserRef = useRef<SessionUserResponse | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [sessionLoadError, setSessionLoadError] = useState(false);
  const [sessionLoadAttempt, setSessionLoadAttempt] = useState(0);
  const [modalOpen, setModalOpen] = useState(false);
  const [initialAuthMode, setInitialAuthMode] = useState<AuthMode>("login");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [verificationPending, setVerificationPending] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let refreshId = 0;
    let loadedToken = window.localStorage.getItem(sessionStorageKey);

    function acceptResult(id: number, token: string): boolean {
      if (cancelled || id !== refreshId) return false;
      if (window.localStorage.getItem(sessionStorageKey) !== token) {
        void loadHeaderSession();
        return false;
      }
      return true;
    }

    async function loadHeaderSession() {
      const currentRefreshId = ++refreshId;
      const token = window.localStorage.getItem(sessionStorageKey);
      if (token !== loadedToken) {
        loadedToken = token;
        sessionUserRef.current = null;
        setSessionUser(null);
        setSessionLoadError(false);
        setLoaded(false);
      }
      if (!token) {
        sessionUserRef.current = null;
        setSessionUser(null);
        setSessionLoadError(false);
        setLoaded(true);
        return;
      }

      try {
        const payload = await getSession(token);
        if (acceptResult(currentRefreshId, token) && payload.authenticated) {
          sessionUserRef.current = payload.user;
          setSessionUser(payload.user);
          setSessionLoadError(false);
          setLoaded(true);
        }
      } catch (requestError) {
        if (!acceptResult(currentRefreshId, token)) return;
        if (requestError instanceof ApiError && requestError.status === 401) {
          window.localStorage.removeItem(sessionStorageKey);
          window.dispatchEvent(new Event(sessionChangedEvent));
        } else if (sessionUserRef.current === null) {
          setSessionLoadError(true);
        }
        // Keep the existing token during transient network failures.
      }
    }

    const timerId = window.setTimeout(() => {
      void loadHeaderSession();
    }, 0);
    const unsubscribe = subscribeToSessionChanges(() => {
      setError("");
      setNotice("");
      setLoading(false);
      void loadHeaderSession();
    });

    return () => {
      cancelled = true;
      window.clearTimeout(timerId);
      unsubscribe();
    };
  }, [sessionLoadAttempt]);

  function retrySessionLoad() {
    setSessionLoadError(false);
    setLoaded(false);
    setSessionLoadAttempt((attempt) => attempt + 1);
  }

  function closeAuthModal() {
    cancelOperation();
    setLoading(false);
    setModalOpen(false);
  }

  function openAuthModal(nextMode: AuthMode = "login") {
    cancelOperation();
    setLoading(false);
    setInitialAuthMode(nextMode);
    setNotice("");
    setError("");
    setVerificationPending(false);
    setModalOpen(true);
  }

  async function authenticate(values: AuthFormSubmitValues) {
    const operation = beginOperation();
    setError("");
    setNotice("");

    setLoading(true);
    try {
      const payload = await submitAuth(values, { languageTag });
      if (!operation.isCurrent()) return;
      window.localStorage.setItem(sessionStorageKey, payload.token);
      window.dispatchEvent(new Event(sessionChangedEvent));
      sessionUserRef.current = payload.user;
      setSessionUser(payload.user);
      setSessionLoadError(false);
      setLoaded(true);
      if (payload.user.email_verified) {
        setModalOpen(false);
      } else {
        setVerificationPending(true);
      }
    } catch (requestError) {
      if (operation.isCurrent()) {
        setError(t(authErrorMessageKey(requestError)));
      }
    } finally {
      if (operation.isLatest()) setLoading(false);
    }
  }

  return (
    <>
      {sessionLoadError ? (
        <button
          className="btn-secondary nav-account"
          type="button"
          onClick={retrySessionLoad}
        >
          <UserRound size={15} aria-hidden="true" />
          {t("header.account")}
        </button>
      ) : !loaded ? (
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
            onClick={closeAuthModal}
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
                onPasswordResetClick={closeAuthModal}
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
