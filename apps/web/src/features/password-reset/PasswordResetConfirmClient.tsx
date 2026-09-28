"use client";

import { type FormEvent, useEffect, useRef, useState } from "react";
import { ArrowRight, KeyRound } from "lucide-react";
import { useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";
import { confirmPasswordReset } from "@/shared/api/auth";
import { passwordResetErrorMessageKey } from "./errors";

const sessionStorageKey = "anytoolai_session_token_v1";
const sessionChangedEvent = "anytoolai_session_changed";

export function PasswordResetConfirmClient() {
  const t = useTranslations("PasswordReset");
  const tokenRef = useRef("");
  const [password, setPassword] = useState("");
  const [passwordConfirm, setPasswordConfirm] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const fragment = new URLSearchParams(window.location.hash.slice(1));
    const token = fragment.get("token");
    if (!token) {
      return;
    }
    tokenRef.current = token;
    window.history.replaceState(
      window.history.state,
      "",
      `${window.location.pathname}${window.location.search}`
    );
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setNotice("");
    setError("");

    const token = tokenRef.current;
    if (!token) {
      setError(t("confirm.validation.missingToken"));
      return;
    }

    if (password.length < 8) {
      setError(t("confirm.validation.passwordTooShort"));
      return;
    }

    if (password !== passwordConfirm) {
      setError(t("confirm.validation.passwordMismatch"));
      return;
    }

    setLoading(true);
    try {
      await confirmPasswordReset({ token, password });
      tokenRef.current = "";
      window.localStorage.removeItem(sessionStorageKey);
      window.dispatchEvent(new Event(sessionChangedEvent));
      setPassword("");
      setPasswordConfirm("");
      setNotice(t("confirm.notices.success"));
    } catch (requestError) {
      setError(t(passwordResetErrorMessageKey(requestError)));
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="page-section compact auth-page-section">
      <div className="form-panel auth-page-panel">
        <form className="form-grid" onSubmit={submit}>
          <span className="badge badge-running">
            <KeyRound size={12} aria-hidden="true" />
            {t("confirm.badge")}
          </span>
          <h1 className="result-title">{t("confirm.title")}</h1>
          <p className="card-copy">{t("confirm.description")}</p>

          <div aria-live="polite">
            {notice ? <div className="notice">{notice}</div> : null}
            {error ? <div className="notice error">{error}</div> : null}
          </div>

          <label className="field-label">
            {t("confirm.fields.passwordLabel")}
            <input
              className="input"
              type="password"
              autoComplete="new-password"
              placeholder={t("confirm.fields.passwordPlaceholder")}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>

          <label className="field-label">
            {t("confirm.fields.passwordConfirmLabel")}
            <input
              className="input"
              type="password"
              autoComplete="new-password"
              placeholder={t("confirm.fields.passwordConfirmPlaceholder")}
              value={passwordConfirm}
              onChange={(event) => setPasswordConfirm(event.target.value)}
            />
          </label>

          <button
            className="btn-primary"
            type="submit"
            disabled={loading}
          >
            {t("confirm.actions.submit")}
            <ArrowRight size={15} aria-hidden="true" />
          </button>

          <Link className="btn-secondary" href="/auth-checkout">
            {t("confirm.actions.signIn")}
          </Link>
        </form>
      </div>
    </section>
  );
}
