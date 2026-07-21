"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { LogIn, UserRound } from "lucide-react";
import { authErrorMessage, resolveApiBase, submitAuth } from "@/shared/api/auth";
import { AuthForm, AuthFormSubmitValues, AuthMode } from "./AuthForm";

type SessionResponse = {
  authenticated: boolean;
  user?: {
    tenant_id: string;
    region: string;
    user_id: string;
    email: string;
  };
};

const telegramLoginUrl = process.env.NEXT_PUBLIC_TELEGRAM_LOGIN_URL ?? "";
const sessionStorageKey = "anytoolai_session_token_v1";
const sessionChangedEvent = "anytoolai_session_changed";
const requestTimeoutMs = 5000;

export function HeaderAccount() {
  const [email, setEmail] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [initialAuthMode, setInitialAuthMode] = useState<AuthMode>("login");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function loadHeaderSession() {
      const token = window.localStorage.getItem(sessionStorageKey);
      if (!token) {
        setEmail("");
        setLoaded(true);
        return;
      }

      const controller = new AbortController();
      const timeoutId = window.setTimeout(() => controller.abort(), requestTimeoutMs);

      try {
        const response = await fetch(`${resolveApiBase()}/api/auth/session`, {
          headers: { Authorization: `Bearer ${token}` },
          signal: controller.signal
        });

        if (!response.ok) {
          window.localStorage.removeItem(sessionStorageKey);
          window.dispatchEvent(new Event(sessionChangedEvent));
          setEmail("");
          return;
        }

        const payload = (await response.json()) as SessionResponse;
        if (!cancelled && payload.authenticated && payload.user?.email) {
          setEmail(payload.user.email);
        } else {
          window.localStorage.removeItem(sessionStorageKey);
          window.dispatchEvent(new Event(sessionChangedEvent));
          setEmail("");
        }
      } catch {
        // Keep the existing token during transient network failures.
      } finally {
        window.clearTimeout(timeoutId);
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
    setModalOpen(true);
  }

  async function authenticate(values: AuthFormSubmitValues) {
    setError("");
    setNotice("");

    setLoading(true);
    try {
      const payload = await submitAuth(values);
      window.localStorage.setItem(sessionStorageKey, payload.token);
      window.dispatchEvent(new Event(sessionChangedEvent));
      setEmail(payload.user.email);
      setModalOpen(false);
    } catch (requestError) {
      setError(authErrorMessage(requestError));
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      {!loaded ? (
        <button className="btn-secondary nav-account" type="button" disabled>
          <UserRound size={15} aria-hidden="true" />
          Аккаунт
        </button>
      ) : email ? (
        <Link className="btn-secondary nav-account" href="/ru/account">
          <UserRound size={15} aria-hidden="true" />
          <span className="nav-account-email">{email}</span>
          <small>статус подписки</small>
        </Link>
      ) : (
        <button
          className="btn-primary nav-account"
          type="button"
          onClick={() => openAuthModal("login")}
        >
          <LogIn size={15} aria-hidden="true" />
          Войти
        </button>
      )}

      {modalOpen ? (
        <>
          <button
            className="auth-modal-overlay"
            type="button"
            aria-label="Закрыть окно входа"
            onClick={() => setModalOpen(false)}
          />
          <div
            className="form-panel auth-modal-panel auth-header-modal"
            role="dialog"
            aria-modal="true"
            aria-label="Вход в аккаунт"
          >
            <AuthForm
              title="Вход или регистрация"
              badgeIcon={<UserRound size={12} aria-hidden="true" />}
              initialMode={initialAuthMode}
              modeOrder={["login", "register"]}
              notice={notice}
              error={error}
              loading={loading}
              personalConsentError="Нужно дать согласие на обработку персональных данных."
              offerConsentError="Нужно принять условия оферты."
              telegramLoginUrl={telegramLoginUrl}
              onModeChange={() => {
                setNotice("");
                setError("");
              }}
              onBeforeSubmit={() => {
                setError("");
                setNotice("");
              }}
              onValidationError={setError}
              onSubmit={authenticate}
            />
          </div>
        </>
      ) : null}
    </>
  );
}
