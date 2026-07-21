"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowRight, LogIn, UserRound } from "lucide-react";

type SessionResponse = {
  authenticated: boolean;
  user?: {
    tenant_id: string;
    region: string;
    user_id: string;
    email: string;
  };
};

type AuthResponse = {
  status: string;
  token: string;
  user: {
    tenant_id: string;
    region: string;
    user_id: string;
    email: string;
  };
};

const configuredApiBase =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const telegramLoginUrl = process.env.NEXT_PUBLIC_TELEGRAM_LOGIN_URL ?? "";
const sessionStorageKey = "anytoolai_session_token_v1";
const sessionChangedEvent = "anytoolai_session_changed";
const requestTimeoutMs = 5000;

function resolveApiBase(): string {
  if (typeof window === "undefined") {
    return configuredApiBase;
  }

  try {
    const url = new URL(configuredApiBase);
    const isLocalApiHost =
      url.hostname === "localhost" || url.hostname === "127.0.0.1";
    const isLocalBrowserHost =
      window.location.hostname === "localhost" ||
      window.location.hostname === "127.0.0.1";

    if (isLocalApiHost && !isLocalBrowserHost) {
      url.hostname = window.location.hostname;
    }

    return url.toString().replace(/\/$/, "");
  } catch {
    return configuredApiBase.replace(/\/$/, "");
  }
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), requestTimeoutMs);
  const response = await fetch(`${resolveApiBase()}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify(body),
    signal: controller.signal
  }).finally(() => window.clearTimeout(timeoutId));

  if (!response.ok) {
    throw new Error(`${response.status}:${await response.text()}`);
  }

  return response.json() as Promise<T>;
}

export function HeaderAccount() {
  const [email, setEmail] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [mode, setMode] = useState<"login" | "register">("login");
  const [formEmail, setFormEmail] = useState("");
  const [password, setPassword] = useState("");
  const [passwordConfirm, setPasswordConfirm] = useState("");
  const [personalConsent, setPersonalConsent] = useState(false);
  const [offerConsent, setOfferConsent] = useState(false);
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

  function openAuthModal(nextMode: "login" | "register" = "login") {
    setMode(nextMode);
    setNotice("");
    setError("");
    setModalOpen(true);
  }

  async function authenticate() {
    setError("");
    setNotice("");

    if (!formEmail.includes("@")) {
      setError("Укажите корректный email.");
      return;
    }

    if (password.length < 8) {
      setError("Пароль должен содержать не менее 8 символов.");
      return;
    }

    if (mode === "register" && password !== passwordConfirm) {
      setError("Пароли не совпадают.");
      return;
    }

    if (mode === "register" && !personalConsent) {
      setError("Нужно дать согласие на обработку персональных данных.");
      return;
    }

    if (mode === "register" && !offerConsent) {
      setError("Нужно принять условия оферты.");
      return;
    }

    setLoading(true);
    try {
      const payload =
        mode === "register"
          ? await postJson<AuthResponse>("/api/auth/register", {
              email: formEmail,
              password,
              personal_consent: personalConsent,
              offer_consent: offerConsent
            })
          : await postJson<AuthResponse>("/api/auth/login", {
              email: formEmail,
              password
            });

      window.localStorage.setItem(sessionStorageKey, payload.token);
      window.dispatchEvent(new Event(sessionChangedEvent));
      setEmail(payload.user.email);
      setPassword("");
      setPasswordConfirm("");
      setModalOpen(false);
    } catch (requestError) {
      const message =
        requestError instanceof Error ? requestError.message : "auth_error";
      if (message.includes("409")) {
        setError("Аккаунт с таким email уже существует. Попробуйте войти.");
      } else if (message.includes("401")) {
        setError("Неверный email или пароль.");
      } else {
        setError("Не удалось выполнить авторизацию. Попробуйте ещё раз.");
      }
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
            <div className="form-grid">
              <span className="badge badge-running">
                <UserRound size={12} aria-hidden="true" />
                Единый аккаунт
              </span>
              <h2>Вход или регистрация</h2>
              {notice ? <div className="notice">{notice}</div> : null}
              {error ? <div className="notice error">{error}</div> : null}

              <div className="auth-mode-row">
                <button
                  className={mode === "login" ? "btn-primary" : "btn-secondary"}
                  type="button"
                  onClick={() => openAuthModal("login")}
                >
                  Вход
                </button>
                <button
                  className={
                    mode === "register" ? "btn-primary" : "btn-secondary"
                  }
                  type="button"
                  onClick={() => openAuthModal("register")}
                >
                  Регистрация
                </button>
              </div>

              <label className="field-label">
                Email
                <input
                  className="input"
                  type="email"
                  autoComplete="email"
                  placeholder="user@example.com"
                  value={formEmail}
                  onChange={(event) => setFormEmail(event.target.value)}
                />
              </label>

              <label className="field-label">
                Пароль
                <input
                  className="input"
                  type="password"
                  autoComplete={
                    mode === "register" ? "new-password" : "current-password"
                  }
                  placeholder="Не менее 8 символов"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                />
              </label>

              {mode === "register" ? (
                <>
                  <label className="field-label">
                    Повторите пароль
                    <input
                      className="input"
                      type="password"
                      autoComplete="new-password"
                      placeholder="Введите пароль ещё раз"
                      value={passwordConfirm}
                      onChange={(event) =>
                        setPasswordConfirm(event.target.value)
                      }
                    />
                  </label>

                  <label className="checkbox-label">
                    <input
                      type="checkbox"
                      checked={personalConsent}
                      onChange={(event) =>
                        setPersonalConsent(event.target.checked)
                      }
                    />
                    <span>
                      Я даю согласие на обработку персональных данных в
                      соответствии с{" "}
                      <Link
                        className="inline-link"
                        href="/ru/consent-personal-data"
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        Согласием на обработку персональных данных
                      </Link>{" "}
                      и{" "}
                      <Link
                        className="inline-link"
                        href="/ru/privacy"
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        Политикой в отношении обработки персональных данных
                      </Link>
                      .
                    </span>
                  </label>

                  <label className="checkbox-label">
                    <input
                      type="checkbox"
                      checked={offerConsent}
                      onChange={(event) => setOfferConsent(event.target.checked)}
                    />
                    <span>
                      Я принимаю условия{" "}
                      <Link
                        className="inline-link"
                        href="/ru/offer"
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        Публичной оферты
                      </Link>
                      .
                    </span>
                  </label>
                </>
              ) : null}

              <button
                className="btn-primary"
                type="button"
                onClick={authenticate}
                disabled={loading}
              >
                {mode === "register" ? "Создать аккаунт" : "Войти"}
                <ArrowRight size={15} aria-hidden="true" />
              </button>

              {telegramLoginUrl ? (
                <a className="btn-secondary telegram-button" href={telegramLoginUrl}>
                  Войти через Telegram
                </a>
              ) : null}
            </div>
          </div>
        </>
      ) : null}
    </>
  );
}
