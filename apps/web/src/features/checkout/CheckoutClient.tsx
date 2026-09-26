"use client";

import { useEffect, useState } from "react";
import { LogOut, ShieldCheck, UserRound } from "lucide-react";
import { Link } from "@/i18n/navigation";
import {
  authErrorMessage,
  decodeAuthSessionResponse,
  decodeLogoutResponse,
  getJson,
  postJson,
  sessionChangedEvent,
  sessionStorageKey,
  submitAuth,
  type AuthUser
} from "@/shared/api/auth";
import { AuthForm, type AuthFormSubmitValues } from "@/shared/ui";

const telegramLoginUrl = process.env.NEXT_PUBLIC_TELEGRAM_LOGIN_URL ?? "";

export function CheckoutClient() {
  const [sessionUser, setSessionUser] = useState<AuthUser | null>(null);
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
      const response = await submitAuth(values);
      window.localStorage.setItem(sessionStorageKey, response.token);
      window.dispatchEvent(new Event(sessionChangedEvent));
      setSessionUser(response.user);
      setNotice(
        values.mode === "register"
          ? "Аккаунт создан. Вход выполнен."
          : "Вход выполнен."
      );
    } catch (requestError) {
      setError(authErrorMessage(requestError));
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
      setNotice("Вы вышли из аккаунта.");
      setError("");
      setLoading(false);
    }
  }

  if (!sessionResolved) {
    return (
      <section className="page-section compact">
        <div className="form-panel" role="status">
          Проверяем сессию...
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
                Вход выполнен
              </span>
              <h1>Аккаунт AnytoolAI</h1>
              <p className="card-copy">{sessionUser.email}</p>
              {notice ? <div className="notice">{notice}</div> : null}
              <div className="hero-actions">
                <Link className="btn-primary" href="/account">
                  Открыть аккаунт
                </Link>
                <button
                  className="btn-secondary"
                  type="button"
                  disabled={loading}
                  onClick={() => void logout()}
                >
                  <LogOut size={15} aria-hidden="true" />
                  Выйти
                </button>
              </div>
            </div>
          ) : (
            <AuthForm
              title="Вход или регистрация"
              badgeIcon={<ShieldCheck size={12} aria-hidden="true" />}
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
                setNotice("");
                setError("");
              }}
              onValidationError={setError}
              onSubmit={authenticate}
            />
          )}
        </article>

        <aside className="form-panel">
          <span className="badge badge-demo">Информация</span>
          <h2 style={{ marginTop: 14 }}>Оплата временно недоступна</h2>
          <p className="card-copy">
            Сейчас портал поддерживает регистрацию, вход, восстановление пароля
            и юридические согласия. Каталог, подписки и оплата будут доступны
            после подключения новой биллинговой системы.
          </p>
        </aside>
      </div>
    </section>
  );
}
