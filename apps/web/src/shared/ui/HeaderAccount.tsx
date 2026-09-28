"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { LogIn, UserRound } from "lucide-react";
import {
  ApiContractError,
  ApiError,
  authErrorMessage,
  decodeAuthSessionResponse,
  getJson,
  sessionChangedEvent,
  sessionStorageKey,
  submitAuth
} from "@/shared/api/auth";
import { AuthForm, AuthFormSubmitValues, AuthMode } from "./AuthForm";

const telegramLoginUrl = process.env.NEXT_PUBLIC_TELEGRAM_LOGIN_URL ?? "";

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
          <small>личный кабинет</small>
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
              onPasswordResetClick={() => setModalOpen(false)}
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
