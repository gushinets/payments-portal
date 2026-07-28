"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { ArrowRight, KeyRound } from "lucide-react";
import {
  confirmPasswordReset,
  passwordResetErrorMessage
} from "@/shared/api/auth";

const sessionStorageKey = "anytoolai_session_token_v1";
const sessionChangedEvent = "anytoolai_session_changed";

export function PasswordResetConfirmClient() {
  const searchParams = useSearchParams();
  const token = searchParams.get("token") ?? "";
  const [password, setPassword] = useState("");
  const [passwordConfirm, setPasswordConfirm] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit() {
    setNotice("");
    setError("");

    if (!token) {
      setError("Ссылка для смены пароля недействительна. Запросите новую ссылку.");
      return;
    }

    if (password.length < 8) {
      setError("Пароль должен содержать не менее 8 символов.");
      return;
    }

    if (password !== passwordConfirm) {
      setError("Пароли не совпадают.");
      return;
    }

    setLoading(true);
    try {
      await confirmPasswordReset({ token, password });
      window.localStorage.removeItem(sessionStorageKey);
      window.dispatchEvent(new Event(sessionChangedEvent));
      setPassword("");
      setPasswordConfirm("");
      setNotice("Пароль изменён. Теперь можно войти с новым паролем.");
    } catch (requestError) {
      setError(passwordResetErrorMessage(requestError));
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="page-section compact auth-page-section">
      <div className="form-panel auth-page-panel">
        <div className="form-grid">
          <span className="badge badge-running">
            <KeyRound size={12} aria-hidden="true" />
            Новый пароль
          </span>
          <h1 className="result-title">Смена пароля</h1>
          <p className="card-copy">
            Задайте новый пароль для аккаунта AnytoolAI. После смены активные
            сессии будут завершены.
          </p>

          <div aria-live="polite">
            {notice ? <div className="notice">{notice}</div> : null}
            {error ? <div className="notice error">{error}</div> : null}
          </div>

          <label className="field-label">
            Новый пароль
            <input
              className="input"
              type="password"
              autoComplete="new-password"
              placeholder="Не менее 8 символов"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>

          <label className="field-label">
            Повторите пароль
            <input
              className="input"
              type="password"
              autoComplete="new-password"
              placeholder="Введите пароль ещё раз"
              value={passwordConfirm}
              onChange={(event) => setPasswordConfirm(event.target.value)}
            />
          </label>

          <button
            className="btn-primary"
            type="button"
            onClick={() => {
              void submit();
            }}
            disabled={loading}
          >
            Сменить пароль
            <ArrowRight size={15} aria-hidden="true" />
          </button>

          <Link className="btn-secondary" href="/ru/auth-checkout">
            Перейти ко входу
          </Link>
        </div>
      </div>
    </section>
  );
}
