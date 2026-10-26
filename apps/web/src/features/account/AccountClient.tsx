"use client";

import { useEffect, useRef, useState } from "react";
import { Clock3, LogOut, ShieldCheck, UserRound } from "lucide-react";
import { useTranslations } from "next-intl";
import { BillingAccount } from "@/features/billing";
import { CatalogPreviewClient } from "@/features/catalog";
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
import {
  subscribeToSessionChanges,
  useSessionOperation
} from "@/shared/session/use-session-operation";

const telegramLoginUrl = process.env.NEXT_PUBLIC_TELEGRAM_LOGIN_URL ?? "";

type AccountState =
  | { status: "loading" }
  | { status: "signed_out" }
  | { status: "session_error"; token: string }
  | { status: "authenticated"; user: SessionUserResponse };

export function AccountClient({ languageTag }: { languageTag: string }) {
  const t = useTranslations("Account");
  const authT = useTranslations("Auth");
  const { begin: beginOperation, beginAuth } = useSessionOperation();
  const skipSessionRefreshRef = useRef(false);
  const [accountState, setAccountState] = useState<AccountState>({
    status: "loading"
  });
  const [authLoading, setAuthLoading] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [sessionLoadAttempt, setSessionLoadAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let refreshId = 0;

    function acceptResult(id: number, token: string): boolean {
      if (cancelled || id !== refreshId) return false;
      if (window.localStorage.getItem(sessionStorageKey) !== token) {
        void loadAccount();
        return false;
      }
      return true;
    }

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
          acceptResult(currentRefreshId, token) &&
          session.authenticated
        ) {
          setAccountState({ status: "authenticated", user: session.user });
        }
      } catch (requestError) {
        if (!acceptResult(currentRefreshId, token)) {
          return;
        }

        if (requestError instanceof ApiError && requestError.status === 401) {
          window.localStorage.removeItem(sessionStorageKey);
          notifySessionChanged();
          setAccountState({ status: "signed_out" });
        } else {
          setAccountState({ status: "session_error", token });
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
      setAuthLoading(false);
      void loadAccount();
    }

    const unsubscribe = subscribeToSessionChanges(handleSessionChanged);
    void loadAccount();
    return () => {
      cancelled = true;
      unsubscribe();
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

  function signOutLocally() {
    if (accountState.status !== "session_error") {
      return;
    }

    const token = window.localStorage.getItem(sessionStorageKey);
    setNotice("");
    setError("");
    if (token && token !== accountState.token) {
      retrySessionLoad();
      return;
    }

    if (token === accountState.token) {
      window.localStorage.removeItem(sessionStorageKey);
      notifySessionChanged();
    }
    setAccountState({ status: "signed_out" });
  }

  async function authenticate(values: AuthFormSubmitValues) {
    const operation = beginAuth();
    setNotice("");
    setError("");
    setAuthLoading(true);
    try {
      const response = await submitAuth(values, { languageTag });
      if (!operation.isCurrent()) return;
      window.localStorage.setItem(sessionStorageKey, response.token);
      notifySessionChanged();
      setAccountState({ status: "authenticated", user: response.user });
      setNotice(
        values.mode === "register"
          ? authT("notices.registered")
          : authT("notices.signedIn")
      );
    } catch (requestError) {
      if (operation.isCurrent()) {
        setError(authT(authErrorMessageKey(requestError)));
      }
    } finally {
      if (operation.isLatest()) setAuthLoading(false);
    }
  }

  async function logout() {
    const operation = beginOperation();
    const token = operation.token;
    if (token && window.localStorage.getItem(sessionStorageKey) === token) {
      window.localStorage.removeItem(sessionStorageKey);
      notifySessionChanged();
    }
    if (operation.isLatest()) {
      setAccountState({ status: "signed_out" });
      setNotice(authT("notices.signedOut"));
      setError("");
      setAuthLoading(false);
    }
    try {
      if (token) {
        await logoutSession(token);
      }
    } catch {
      // Local logout is already complete; backend revocation is best-effort.
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
          <button
            className="btn-secondary"
            type="button"
            onClick={signOutLocally}
          >
            {t("sessionError.localSignOutAction")}
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
        <header className="account-heading">
          <div>
            <div className="eyebrow">
              <span className="eyebrow-dot" />
              {t("eyebrow")}
            </div>
            <h1 className="legal-title">{t("title")}</h1>
            <p className="hero-copy">{t("authenticated.description")}</p>
          </div>
        </header>
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
              onClick={() => void logout()}
            >
              <LogOut size={15} aria-hidden="true" />
              {t("authenticated.signOutAction")}
            </button>
          </div>
        </aside>

        <div className="account-workspace">
          <BillingAccount key={accountState.user.user_id} userId={accountState.user.user_id} emailVerified={accountState.user.email_verified} />
          <section
            className="account-products-panel"
            aria-labelledby="account-products-title"
          >
            <div className="account-products-heading">
              <h2 id="account-products-title">{t("products.title")}</h2>
              <p className="card-copy">{t("products.description")}</p>
            </div>
            <CatalogPreviewClient
              headingLevel={3}
              accountStatuses={{
                access: {
                  label: t("products.state.access.label"),
                  description: t("products.state.access.description")
                },
                usage: {
                  label: t("products.state.usage.label"),
                  description: t("products.state.usage.description")
                }
              }}
            />
          </section>
        </div>
      </div>
    </section>
  );
}
