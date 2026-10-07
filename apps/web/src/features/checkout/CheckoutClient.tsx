"use client";

import { useEffect, useState } from "react";
import { LogOut, ShieldCheck, UserRound } from "lucide-react";
import { useTranslations } from "next-intl";
import type { SessionUserResponse } from "@/generated/api-contracts/types.gen";
import { Link } from "@/i18n/navigation";
import {
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

const telegramLoginUrl = process.env.NEXT_PUBLIC_TELEGRAM_LOGIN_URL ?? "";

export function CheckoutClient({ languageTag }: { languageTag: string }) {
  const authT = useTranslations("Auth");
  const checkoutT = useTranslations("Checkout");
  const [sessionUser, setSessionUser] =
    useState<SessionUserResponse | null>(null);
  const [sessionResolved, setSessionResolved] = useState(false);
  const [loading, setLoading] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

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
        const session = await getSession(token);
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
      window.localStorage.setItem(sessionStorageKey, response.token);
      window.dispatchEvent(new Event(sessionChangedEvent));
      setSessionUser(response.user);
      setNotice(
        values.mode === "register"
          ? authT("notices.registered")
          : authT("notices.signedIn")
      );
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
        await logoutSession(token);
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
              {!sessionUser.email_verified ? (
                <EmailVerificationPending languageTag={languageTag} />
              ) : null}
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
              loading={loading}
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
