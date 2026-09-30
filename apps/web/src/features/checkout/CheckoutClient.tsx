"use client";

import { useEffect, useState } from "react";
import { LogOut, ShieldCheck, UserRound } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import {
  DEFAULT_ROUTE_LOCALE,
  isRouteLocale,
  LANGUAGE_TAG_BY_ROUTE_LOCALE
} from "@/generated/locales";
import { Link } from "@/i18n/navigation";
import {
  decodeAuthSessionResponse,
  decodeLogoutResponse,
  getJson,
  postJson,
  requestEmailVerification,
  sessionChangedEvent,
  sessionStorageKey,
  submitAuth,
  type AuthUser
} from "@/shared/api/auth";
import {
  AuthForm,
  authErrorMessageKey,
  type AuthFormSubmitValues
} from "@/shared/ui";
import { isEmailVerificationRequiredError } from "@/shared/ui/auth-errors";

const telegramLoginUrl = process.env.NEXT_PUBLIC_TELEGRAM_LOGIN_URL ?? "";

export function CheckoutClient() {
  const authT = useTranslations("Auth");
  const checkoutT = useTranslations("Checkout");
  const locale = useLocale();
  const languageTag = LANGUAGE_TAG_BY_ROUTE_LOCALE[
    isRouteLocale(locale) ? locale : DEFAULT_ROUTE_LOCALE
  ];
  const [sessionUser, setSessionUser] = useState<AuthUser | null>(null);
  const [sessionResolved, setSessionResolved] = useState(false);
  const [loading, setLoading] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [verificationRequired, setVerificationRequired] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let refreshId = 0;

    async function loadSession() {
      const currentRefreshId = ++refreshId;
      const token = window.localStorage.getItem(sessionStorageKey);
      if (!token) {
        if (!cancelled && currentRefreshId === refreshId) {
          setSessionUser(null);
          setSessionResolved(true);
        }
        return;
      }

      try {
        const session = await getJson(
          "/api/auth/session",
          token,
          decodeAuthSessionResponse
        );
        if (
          !cancelled &&
          currentRefreshId === refreshId &&
          session.authenticated
        ) {
          setSessionUser(session.user);
        }
      } catch {
        if (window.localStorage.getItem(sessionStorageKey) === token) {
          window.localStorage.removeItem(sessionStorageKey);
          window.dispatchEvent(new Event(sessionChangedEvent));
        }
        if (!cancelled && currentRefreshId === refreshId) {
          setSessionUser(null);
        }
      } finally {
        if (!cancelled && currentRefreshId === refreshId) {
          setSessionResolved(true);
        }
      }
    }

    function handleSessionChanged() {
      void loadSession();
    }

    window.addEventListener(sessionChangedEvent, handleSessionChanged);
    void loadSession();
    return () => {
      cancelled = true;
      window.removeEventListener(sessionChangedEvent, handleSessionChanged);
    };
  }, []);

  async function authenticate(values: AuthFormSubmitValues) {
    setError("");
    setNotice("");
    setLoading(true);

    try {
      const response = await submitAuth(values, { languageTag });
      if (response.status === "verification_required") {
        setVerificationRequired(true);
        return;
      }
      window.localStorage.setItem(sessionStorageKey, response.token);
      window.dispatchEvent(new Event(sessionChangedEvent));
      setSessionUser(response.user);
      setNotice(
        values.mode === "register"
          ? authT("notices.registered")
          : authT("notices.signedIn")
      );
    } catch (requestError) {
      if (isEmailVerificationRequiredError(requestError)) {
        setVerificationRequired(true);
        return;
      }
      setError(authT(authErrorMessageKey(requestError)));
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
      setNotice(authT("verification.notices.resent"));
    } catch (requestError) {
      setError(authT(authErrorMessageKey(requestError)));
    } finally {
      setLoading(false);
    }
  }

  async function logout() {
    const token = window.localStorage.getItem(sessionStorageKey);
    setLoading(true);
    try {
      if (token) {
        await postJson("/api/auth/logout", {}, decodeLogoutResponse, token);
      }
    } catch {
      // Local session removal still leaves this browser signed out.
    } finally {
      window.localStorage.removeItem(sessionStorageKey);
      window.dispatchEvent(new Event(sessionChangedEvent));
      setSessionUser(null);
      setNotice(authT("notices.signedOut"));
      setError("");
      setLoading(false);
    }
  }

  if (!sessionResolved) {
    return (
      <section className="page-section compact">
        <div className="form-panel" role="status">
          {checkoutT("sessionChecking")}
        </div>
      </section>
    );
  }

  return (
    <section className="page-section compact">
      <div className="checkout-layout auth-only-layout">
        <article className="form-panel">
          {sessionUser ? (
            <div className="form-grid">
              <span className="badge badge-live">
                <UserRound size={12} aria-hidden="true" />
                {checkoutT("authenticatedBadge")}
              </span>
              <h1>{checkoutT("accountTitle")}</h1>
              <p className="card-copy">{sessionUser.email}</p>
              {notice ? <div className="notice">{notice}</div> : null}
              <div className="hero-actions">
                <Link className="btn-primary" href="/account">
                  {checkoutT("openAccountAction")}
                </Link>
                <button
                  className="btn-secondary"
                  type="button"
                  disabled={loading}
                  onClick={() => void logout()}
                >
                  <LogOut size={15} aria-hidden="true" />
                  {checkoutT("signOutAction")}
                </button>
              </div>
            </div>
          ) : (
            <AuthForm
              title={authT("dialogTitle")}
              badgeIcon={<ShieldCheck size={12} aria-hidden="true" />}
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
              onBeforeSubmit={() => {
                setNotice("");
                setError("");
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
          )}
        </article>

        <aside className="form-panel">
          <span className="badge badge-demo">
            {checkoutT("unavailable.badge")}
          </span>
          <h2 style={{ marginTop: 14 }}>{checkoutT("unavailable.title")}</h2>
          <p className="card-copy">{checkoutT("unavailable.description")}</p>
        </aside>
      </div>
    </section>
  );
}
