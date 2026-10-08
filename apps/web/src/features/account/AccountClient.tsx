"use client";

import { useEffect, useRef, useState } from "react";
import { Clock3, LogOut, ShieldCheck, UserRound } from "lucide-react";
import { useTranslations } from "next-intl";
import { productPresentation } from "@/features/catalog";
import type { SessionUserResponse } from "@/generated/api-contracts/types.gen";
import {
  ApiError,
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
import { AccountProductCard } from "./AccountProductCard";

const telegramLoginUrl = process.env.NEXT_PUBLIC_TELEGRAM_LOGIN_URL ?? "";

type AccountState =
  | { status: "loading" }
  | { status: "signed_out" }
  | { status: "session_error" }
  | { status: "authenticated"; user: SessionUserResponse };

export function AccountClient({ languageTag }: { languageTag: string }) {
  const t = useTranslations("Account");
  const authT = useTranslations("Auth");
  const skipSessionRefreshRef = useRef(false);
  const [accountState, setAccountState] = useState<AccountState>({
    status: "loading"
  });
  const [loggingOut, setLoggingOut] = useState(false);
  const [authLoading, setAuthLoading] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [sessionLoadAttempt, setSessionLoadAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let refreshId = 0;

    async function loadAccount() {
      const currentRefreshId = ++refreshId;
      const token = window.localStorage.getItem(sessionStorageKey);
      if (!token) {
        if (!cancelled && currentRefreshId === refreshId) {
          setAccountState({ status: "signed_out" });
        }
        return;
      }

      setAccountState({ status: "loading" });
      try {
        const session = await getSession(token);
        if (
          !cancelled &&
          currentRefreshId === refreshId &&
          window.localStorage.getItem(sessionStorageKey) === token &&
          session.authenticated
        ) {
          setAccountState({ status: "authenticated", user: session.user });
        }
      } catch (requestError) {
        if (
          cancelled ||
          currentRefreshId !== refreshId ||
          window.localStorage.getItem(sessionStorageKey) !== token
        ) {
          return;
        }

        if (requestError instanceof ApiError && requestError.status === 401) {
          window.localStorage.removeItem(sessionStorageKey);
          notifySessionChanged();
          setAccountState({ status: "signed_out" });
        } else {
          setAccountState({ status: "session_error" });
        }
      }
    }

    function handleSessionChanged() {
      if (skipSessionRefreshRef.current) {
        skipSessionRefreshRef.current = false;
        refreshId += 1;
        return;
      }
      setNotice("");
      setError("");
      void loadAccount();
    }

    window.addEventListener(sessionChangedEvent, handleSessionChanged);
    void loadAccount();
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
    setAccountState({ status: "loading" });
    setSessionLoadAttempt((attempt) => attempt + 1);
  }

  async function authenticate(values: AuthFormSubmitValues) {
    setNotice("");
    setError("");
    setAuthLoading(true);
    try {
      const response = await submitAuth(values, { languageTag });
      window.localStorage.setItem(sessionStorageKey, response.token);
      notifySessionChanged();
      setAccountState({ status: "authenticated", user: response.user });
      setNotice(
        values.mode === "register"
          ? authT("notices.registered")
          : authT("notices.signedIn")
      );
    } catch (requestError) {
      setError(authT(authErrorMessageKey(requestError)));
    } finally {
      setAuthLoading(false);
    }
  }

  async function logout() {
    const token = window.localStorage.getItem(sessionStorageKey);
    setLoggingOut(true);
    try {
      if (token) {
        await logoutSession(token);
      }
    } catch {
      // Local session removal still leaves this browser signed out.
    } finally {
      if (window.localStorage.getItem(sessionStorageKey) === token) {
        window.localStorage.removeItem(sessionStorageKey);
        notifySessionChanged();
        setAccountState({ status: "signed_out" });
        setNotice(authT("notices.signedOut"));
        setError("");
      }
      setLoggingOut(false);
    }
  }

  if (accountState.status === "loading") {
    return (
      <section className="page-section compact">
        <div className="form-panel" role="status">
          {t("loading")}
        </div>
      </section>
    );
  }

  if (accountState.status === "session_error") {
    return (
      <section className="page-section compact auth-page-section">
        <div className="form-panel auth-page-panel form-grid">
          <span className="badge badge-running">
            <UserRound size={12} aria-hidden="true" />
            {t("badge")}
          </span>
          <h1 className="legal-title">{t("title")}</h1>
          <div className="notice error" role="alert">
            {t("sessionError.notice")}
          </div>
          <button
            className="btn-primary"
            type="button"
            onClick={retrySessionLoad}
          >
            {t("sessionError.retryAction")}
          </button>
        </div>
      </section>
    );
  }

  if (accountState.status === "signed_out") {
    return (
      <section className="page-section compact auth-page-section">
        <div className="form-panel auth-page-panel account-auth-panel">
          <h1 className="legal-title">{t("title")}</h1>
          <p className="card-copy">{t("signedOut.notice")}</p>
          <AuthForm
            title={authT("dialogTitle")}
            badgeIcon={<ShieldCheck size={12} aria-hidden="true" />}
            notice={notice}
            error={error}
            loading={authLoading}
            telegramLoginUrl={telegramLoginUrl}
            onModeChange={() => {
              setNotice("");
              setError("");
            }}
            onBeforeSubmit={() => {
              setNotice("");
              setError("");
            }}
            onValidationError={setError}
            onSubmit={authenticate}
          />
        </div>
      </section>
    );
  }

  return (
    <section className="account-dashboard">
      <div className="account-layout">
        <aside
          className="account-summary-panel"
          aria-labelledby="account-summary-title"
        >
          <h2 id="account-summary-title">
            {t("authenticated.summaryTitle")}
          </h2>
          <dl className="account-identity">
            <dt>{t("authenticated.emailLabel")}</dt>
            <dd className="account-summary-email">{accountState.user.email}</dd>
          </dl>
          <span
            className={`badge ${accountState.user.email_verified ? "badge-live" : "badge-demo"}`}
          >
            {accountState.user.email_verified ? (
              <ShieldCheck size={12} aria-hidden="true" />
            ) : (
              <Clock3 size={12} aria-hidden="true" />
            )}
            {t(
              accountState.user.email_verified
                ? "authenticated.emailVerified"
                : "authenticated.emailUnverified"
            )}
          </span>
          <div aria-live="polite">
            {notice ? <div className="notice">{notice}</div> : null}
          </div>
          {!accountState.user.email_verified ? (
            <EmailVerificationPending languageTag={languageTag} />
          ) : null}
          <div className="account-summary-actions">
            <button
              className="btn-secondary"
              type="button"
              disabled={loggingOut}
              onClick={() => void logout()}
            >
              <LogOut size={15} aria-hidden="true" />
              {t("authenticated.signOutAction")}
            </button>
          </div>
        </aside>

        <div className="account-workspace">
          <header className="account-heading">
            <div className="eyebrow">
              <span className="eyebrow-dot" />
              {t("eyebrow")}
            </div>
            <h1 className="legal-title">{t("title")}</h1>
            <p className="hero-copy">{t("authenticated.description")}</p>
          </header>

          <section
            className="account-products-panel"
            aria-labelledby="account-products-title"
          >
            <div className="account-products-heading">
              <h2 id="account-products-title">{t("products.title")}</h2>
              <p className="card-copy">{t("products.description")}</p>
            </div>
            <div className="account-products-grid">
              {productPresentation.map((product) => (
                <AccountProductCard product={product} key={product.slug} />
              ))}
            </div>
          </section>
        </div>
      </div>
    </section>
  );
}
