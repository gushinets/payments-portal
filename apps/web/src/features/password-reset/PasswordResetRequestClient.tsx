"use client";

import Link from "next/link";
import { type FormEvent, useState } from "react";
import { ArrowRight, Mail } from "lucide-react";
import {
  passwordResetErrorMessage,
  requestPasswordReset
} from "@/shared/api/auth";

export function PasswordResetRequestClient() {
  const [email, setEmail] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setNotice("");
    setError("");

    if (!email.includes("@")) {
      setError("Укажите корректный email.");
      return;
    }

    setLoading(true);
    try {
      await requestPasswordReset({ email });
      setNotice(
        "Если аккаунт с таким email существует, мы отправили ссылку для смены пароля."
      );
    } catch (requestError) {
      setError(passwordResetErrorMessage(requestError));
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="page-section compact auth-page-section">
      <div className="form-panel auth-page-panel">
        <form className="form-grid" onSubmit={submit}>
          <span className="badge badge-running">
            <Mail size={12} aria-hidden="true" />
            Восстановление доступа
          </span>
          <h1 className="result-title">Сброс пароля</h1>
          <p className="card-copy">
            Введите email аккаунта AnytoolAI. Мы отправим ссылку для смены пароля.
          </p>

          <div aria-live="polite">
            {notice ? <div className="notice">{notice}</div> : null}
            {error ? <div className="notice error">{error}</div> : null}
          </div>

          <label className="field-label">
            Email
            <input
              className="input"
              type="email"
              autoComplete="email"
              placeholder="user@example.com"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
          </label>

          <button
            className="btn-primary"
            type="submit"
            disabled={loading}
          >
            Отправить ссылку
            <ArrowRight size={15} aria-hidden="true" />
          </button>

          <Link className="btn-secondary" href="/ru/auth-checkout">
            Вернуться ко входу
          </Link>
        </form>
      </div>
    </section>
  );
}
