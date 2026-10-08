"use client";

import { type ReactNode, useEffect, useRef, useState } from "react";
import { LogOut, MailCheck } from "lucide-react";
import { useTranslations } from "next-intl";
import type { SessionUserResponse } from "@/generated/api-contracts/types.gen";
import { Link } from "@/i18n/navigation";
import {
  ApiError,
  confirmEmailVerification,
  getSession,
  logoutSession,
  sessionChangedEvent,
  sessionStorageKey,
  submitAuth
} from "@/shared/api/auth";
import {
  AuthForm,
  authErrorMessageKey,
  EmailVerificationPending,
  type AuthFormSubmitValues
} from "@/shared/ui";
import {
  emailVerificationErrorMessageKey,
  type EmailVerificationErrorMessageKey
} from "./errors";

type VerificationState =
  | { status: "loading" }
  | { status: "signed_out" }
  | { status: "session_error"; messageKey: EmailVerificationErrorMessageKey }
  | { status: "authenticated"; user: SessionUserResponse }
  | { status: "verified" };

export function EmailVerificationClient({
  languageTag
}: {
  languageTag: string;
}) {
  const t = useTranslations("EmailVerification");
  const authT = useTranslations("Auth");
  const verificationTokenRef = useRef("");
  const fragmentReadRef = useRef(false);
  const skipSessionRefreshRef = useRef(false);
  const [hasVerificationToken, setHasVerificationToken] = useState(false);
  const [verificationState, setVerificationState] =
    useState<VerificationState>({ status: "loading" });
  const [authError, setAuthError] = useState("");
  const [verificationError, setVerificationError] = useState("");
  const [loading, setLoading] = useState(false);
  const [sessionLoadAttempt, setSessionLoadAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    if (!fragmentReadRef.current) {
      fragmentReadRef.current = true;
      const fragment = new URLSearchParams(window.location.hash.slice(1));
      const verificationToken = fragment.get("token") ?? "";
      verificationTokenRef.current = verificationToken;
      setHasVerificationToken(Boolean(verificationToken));

      if (window.location.hash) {
        window.history.replaceState(
          window.history.state,
          "",
          `${window.location.pathname}${window.location.search}`
        );
      }
    }

    async function loadSession() {
      const sessionToken = window.localStorage.getItem(sessionStorageKey);
      if (!sessionToken) {
        if (!cancelled) {
          setVerificationState({ status: "signed_out" });
        }
        return;
      }

      try {
        const session = await getSession(sessionToken);
        if (
          !cancelled &&
          window.localStorage.getItem(sessionStorageKey) === sessionToken
        ) {
          setVerificationState({
            status: "authenticated",
            user: session.user
          });
        }
      } catch (requestError) {
        const isCurrentSession =
          window.localStorage.getItem(sessionStorageKey) === sessionToken;
        if (
          !cancelled &&
          isCurrentSession &&
          requestError instanceof ApiError &&
          requestError.status === 401
        ) {
          window.localStorage.removeItem(sessionStorageKey);
          notifySessionChanged();
          if (!cancelled) {
            setVerificationState({ status: "signed_out" });
          }
          return;
        }
        if (!cancelled && isCurrentSession) {
          setVerificationState({
            status: "session_error",
            messageKey: emailVerificationErrorMessageKey(requestError)
          });
        }
      }
    }

    function handleSessionChanged() {
      if (skipSessionRefreshRef.current) {
        skipSessionRefreshRef.current = false;
        return;
      }
      if (!cancelled) {
        setVerificationState({ status: "loading" });
        void loadSession();
      }
    }

    void loadSession();
    window.addEventListener(sessionChangedEvent, handleSessionChanged);
    return () => {
      cancelled = true;
      window.removeEventListener(sessionChangedEvent, handleSessionChanged);
    };
  }, [sessionLoadAttempt]);

  function notifySessionChanged() {
    skipSessionRefreshRef.current = true;
    window.dispatchEvent(new Event(sessionChangedEvent));
  }

  function retrySessionLoad() {
    setVerificationState({ status: "loading" });
    setSessionLoadAttempt((attempt) => attempt + 1);
  }

  async function authenticate(values: AuthFormSubmitValues) {
    setAuthError("");
    setLoading(true);
    try {
      const response = await submitAuth(values, { languageTag });
      window.localStorage.setItem(sessionStorageKey, response.token);
      notifySessionChanged();
      setVerificationState({ status: "authenticated", user: response.user });
    } catch (requestError) {
      setAuthError(authT(authErrorMessageKey(requestError)));
    } finally {
      setLoading(false);
    }
  }

  async function switchAccount() {
    const sessionToken = window.localStorage.getItem(sessionStorageKey);
    setLoading(true);
    try {
      if (sessionToken) {
        await logoutSession(sessionToken);
      }
    } catch {
      // Removing the local bearer still leaves this browser signed out.
    } finally {
      if (window.localStorage.getItem(sessionStorageKey) === sessionToken) {
        window.localStorage.removeItem(sessionStorageKey);
        notifySessionChanged();
        setVerificationState({ status: "signed_out" });
        setAuthError("");
        setVerificationError("");
      }
      setLoading(false);
    }
  }

  async function verify() {
    const sessionToken = window.localStorage.getItem(sessionStorageKey);
    const verificationToken = verificationTokenRef.current;
    setVerificationError("");

    if (!sessionToken) {
      setVerificationState({ status: "signed_out" });
      setVerificationError(t("errors.signInRequired"));
      return;
    }
    if (!verificationToken) {
      setHasVerificationToken(false);
      setVerificationError(t("verify.missingToken"));
      return;
    }

    setLoading(true);
    try {
      await confirmEmailVerification(sessionToken, verificationToken);
      if (window.localStorage.getItem(sessionStorageKey) !== sessionToken) {
        return;
      }
      verificationTokenRef.current = "";
      setHasVerificationToken(false);
      setVerificationState({ status: "verified" });
      notifySessionChanged();
    } catch (requestError) {
      if (window.localStorage.getItem(sessionStorageKey) !== sessionToken) {
        return;
      }
      if (requestError instanceof ApiError && requestError.status === 401) {
        window.localStorage.removeItem(sessionStorageKey);
        notifySessionChanged();
        setVerificationState({ status: "signed_out" });
      }
      setVerificationError(t(emailVerificationErrorMessageKey(requestError)));
    } finally {
      setLoading(false);
    }
  }

  if (verificationState.status === "loading") {
    return (
      <section className="page-section compact auth-page-section">
        <div className="form-panel auth-page-panel" role="status">
          {t("verify.loading")}
        </div>
      </section>
    );
  }

  if (verificationState.status === "verified") {
    return (
      <VerificationPanel title={t("verify.successTitle")}>
        <div className="notice">{t("verify.successDescription")}</div>
        <Link className="btn-primary" href="/account">
          {t("verify.openAccount")}
        </Link>
      </VerificationPanel>
    );
  }

  if (verificationState.status === "session_error") {
    return (
      <VerificationPanel title={t("verify.title")}>
        <div className="notice" role="alert">
          {t(verificationState.messageKey)}
        </div>
        <button
          className="btn-primary"
          type="button"
          onClick={retrySessionLoad}
        >
          {t("verify.retrySession")}
        </button>
      </VerificationPanel>
    );
  }

  if (verificationState.status === "signed_out") {
    return (
      <section className="page-section compact auth-page-section">
        <div className="form-panel auth-page-panel">
          {hasVerificationToken ? (
            <AuthForm
              title={t("verify.signInTitle")}
              badgeIcon={<MailCheck size={12} aria-hidden="true" />}
              initialMode="login"
              modeOrder={["login"]}
              prompt={<p className="card-copy">{t("verify.signInWithToken")}</p>}
              error={authError || verificationError}
              loading={loading}
              onBeforeSubmit={() => {
                setAuthError("");
                setVerificationError("");
              }}
              onValidationError={setAuthError}
              onSubmit={authenticate}
            />
          ) : (
            <div className="form-grid">
              <span className="badge badge-running">
                <MailCheck size={12} aria-hidden="true" />
                {t("verify.badge")}
              </span>
              <h1>{t("verify.title")}</h1>
              <div className="notice">{t("verify.signedOutWithoutToken")}</div>
              <Link className="btn-primary" href="/auth-checkout">
                {t("verify.signInAction")}
              </Link>
            </div>
          )}
        </div>
      </section>
    );
  }

  if (verificationState.user.email_verified && !hasVerificationToken) {
    return (
      <VerificationPanel title={t("verify.alreadyVerifiedTitle")}>
        <div className="notice">{t("verify.alreadyVerifiedDescription")}</div>
        <Link className="btn-primary" href="/account">
          {t("verify.openAccount")}
        </Link>
      </VerificationPanel>
    );
  }

  if (!hasVerificationToken) {
    return (
      <section className="page-section compact auth-page-section">
        <div className="form-panel auth-page-panel">
          <EmailVerificationPending languageTag={languageTag} />
          <p className="card-copy">{t("verify.missingToken")}</p>
        </div>
      </section>
    );
  }

  return (
    <VerificationPanel title={t("verify.title")}>
      <p className="card-copy">{t("verify.description")}</p>
      <p className="card-copy">{verificationState.user.email}</p>
      <div aria-live="polite">
        {verificationError ? (
          <div className="notice error">{verificationError}</div>
        ) : null}
      </div>
      <div className="hero-actions">
        <button
          className="btn-primary"
          type="button"
          disabled={loading}
          onClick={() => void verify()}
        >
          {loading ? t("verify.verifying") : t("verify.action")}
        </button>
        <button
          className="btn-secondary"
          type="button"
          disabled={loading}
          onClick={() => void switchAccount()}
        >
          <LogOut size={15} aria-hidden="true" />
          {t("verify.switchAccountAction")}
        </button>
      </div>
    </VerificationPanel>
  );
}

function VerificationPanel({
  title,
  children
}: {
  title: string;
  children: ReactNode;
}) {
  const t = useTranslations("EmailVerification");

  return (
    <section className="page-section compact auth-page-section">
      <div className="form-panel auth-page-panel form-grid">
        <span className="badge badge-running">
          <MailCheck size={12} aria-hidden="true" />
          {t("verify.badge")}
        </span>
        <h1>{title}</h1>
        {children}
      </div>
    </section>
  );
}
