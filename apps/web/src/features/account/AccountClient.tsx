"use client";

import { useEffect, useState } from "react";
import { LogOut, UserRound } from "lucide-react";
import { useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";
import {
  decodeAuthSessionResponse,
  decodeLogoutResponse,
  getJson,
  postJson,
  sessionChangedEvent,
  sessionStorageKey,
  type AuthUser
} from "@/shared/api/auth";

type AccountState =
  | { status: "loading" }
  | { status: "signed_out" }
  | { status: "authenticated"; user: AuthUser };

export function AccountClient() {
  const t = useTranslations("Account");
  const [accountState, setAccountState] = useState<AccountState>({
    status: "loading"
  });
  const [loggingOut, setLoggingOut] = useState(false);

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
          setAccountState({ status: "authenticated", user: session.user });
        }
      } catch {
        if (window.localStorage.getItem(sessionStorageKey) === token) {
          window.localStorage.removeItem(sessionStorageKey);
          window.dispatchEvent(new Event(sessionChangedEvent));
        }
        if (!cancelled && currentRefreshId === refreshId) {
          setAccountState({ status: "signed_out" });
        }
      }
    }

    function handleSessionChanged() {
      void loadAccount();
    }

    window.addEventListener(sessionChangedEvent, handleSessionChanged);
    void loadAccount();
    return () => {
      cancelled = true;
      window.removeEventListener(sessionChangedEvent, handleSessionChanged);
    };
  }, []);

  async function logout() {
    const token = window.localStorage.getItem(sessionStorageKey);
    setLoggingOut(true);
    try {
      if (token) {
        await postJson("/api/auth/logout", {}, decodeLogoutResponse, token);
      }
    } catch {
      // Local session removal still leaves this browser signed out.
    } finally {
      window.localStorage.removeItem(sessionStorageKey);
      window.dispatchEvent(new Event(sessionChangedEvent));
      setAccountState({ status: "signed_out" });
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

  if (accountState.status === "signed_out") {
    return (
      <section className="page-section compact">
        <div className="form-panel">
          <span className="badge badge-running">
            <UserRound size={12} aria-hidden="true" />
            {t("badge")}
          </span>
          <h1 className="legal-title" style={{ marginTop: 14 }}>
            {t("title")}
          </h1>
          <div className="notice" style={{ marginTop: 20 }}>
            {t("signedOut.notice")}
          </div>
          <div className="hero-actions">
            <Link className="btn-primary" href="/auth-checkout">
              {t("signedOut.action")}
            </Link>
          </div>
        </div>
      </section>
    );
  }

  return (
    <section className="page-section compact">
      <div className="eyebrow">
        <span className="eyebrow-dot" />
        {t("eyebrow")}
      </div>
      <h1 className="legal-title">{t("title")}</h1>
      <p className="hero-copy">{t("authenticated.description")}</p>

      <div className="account-layout">
        <article className="form-panel account-summary-panel">
          <span className="badge badge-live">
            <UserRound size={12} aria-hidden="true" />
            {t("authenticated.badge")}
          </span>
          <h2 style={{ marginTop: 14 }}>{t("authenticated.summaryTitle")}</h2>
          <p className="card-copy account-summary-email">
            {accountState.user.email}
          </p>
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
        </article>

        <aside className="form-panel">
          <span className="badge badge-demo">
            {t("billingUnavailable.badge")}
          </span>
          <h2 style={{ marginTop: 14 }}>
            {t("billingUnavailable.title")}
          </h2>
          <p className="card-copy">{t("billingUnavailable.description")}</p>
        </aside>
      </div>
    </section>
  );
}
