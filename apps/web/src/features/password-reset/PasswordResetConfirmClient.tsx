"use client";

import { type FormEvent, useEffect, useRef, useState } from "react";
import { ArrowRight, KeyRound } from "lucide-react";
import { useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";
import {
  confirmPasswordReset,
  sessionStorageKey,
  sessionChangedEvent
} from "@/shared/api/auth";
import { useSessionOperation } from "@/shared/session/use-session-operation";
import { passwordResetErrorMessageKey } from "./errors";

export function PasswordResetConfirmClient() {
  const { begin: beginOperation } = useSessionOperation();
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

    if (password !== passwordConfirm) {
      setError(t("confirm.validation.passwordMismatch"));
      return;
    }

    const operation = beginOperation();
    setLoading(true);
    try {
      await confirmPasswordReset({ token, password });
      if (!operation.isLatest()) return;
      tokenRef.current = "";
      if (operation.token && operation.isCurrent()) {
        window.localStorage.removeItem(sessionStorageKey);
        window.dispatchEvent(new Event(sessionChangedEvent));
      }
      setPassword("");
      setPasswordConfirm("");
      setNotice(t("confirm.notices.success"));
    } catch (requestError) {
      if (operation.isLatest()) {
        setError(t(passwordResetErrorMessageKey(requestError)));
      }
    } finally {
      if (operation.isLatest()) setLoading(false);
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
              aria-describedby="reset-password-requirements"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>

          <div
            className="password-requirements"
            id="reset-password-requirements"
          >
            <p>{t("confirm.passwordRequirements.label")}</p>
            <ul>
              <li>{t("confirm.passwordRequirements.length")}</li>
              <li>{t("confirm.passwordRequirements.uppercase")}</li>
              <li>{t("confirm.passwordRequirements.lowercase")}</li>
              <li>{t("confirm.passwordRequirements.digit")}</li>
              <li>
                {t("confirm.passwordRequirements.special", {
                  characters: "!@#$%^&*()-_=+[]{}:,.?"
                })}
              </li>
            </ul>
          </div>

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

          <Link className="btn-secondary" href="/account">
            {t("confirm.actions.signIn")}
          </Link>
        </form>
      </div>
    </section>
  );
}
