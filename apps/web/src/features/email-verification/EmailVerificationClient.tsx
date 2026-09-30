"use client";

import { type FormEvent, useEffect, useRef, useState } from "react";
import { ArrowRight, BadgeCheck, Mail } from "lucide-react";
import { useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";
import {
  confirmEmailVerification,
  requestEmailVerification,
  sessionChangedEvent,
  sessionStorageKey
} from "@/shared/api/auth";
import {
  emailVerificationErrorMessageKey,
  isInvalidVerificationTokenError
} from "./errors";

export function EmailVerificationClient({
  languageTag
}: {
  languageTag: string;
}) {
  const t = useTranslations("EmailVerification");
  const tokenRef = useRef("");
  const [ready, setReady] = useState(false);
  const [needsRecovery, setNeedsRecovery] = useState(false);
  const [verified, setVerified] = useState(false);
  const [password, setPassword] = useState("");
  const [email, setEmail] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const fragment = new URLSearchParams(window.location.hash.slice(1));
    const token = fragment.get("token") ?? "";
    window.history.replaceState(
      window.history.state,
      "",
      `${window.location.pathname}${window.location.search}`
    );
    tokenRef.current = token;
    setNeedsRecovery(!token);
    setReady(true);
  }, []);

  async function verify(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setNotice("");
    setError("");

    const token = tokenRef.current;
    if (!token) {
      setNeedsRecovery(true);
      setError(t("validation.missingToken"));
      return;
    }
    if (password.length < 8) {
      setError(t("validation.passwordTooShort"));
      return;
    }

    setLoading(true);
    try {
      const response = await confirmEmailVerification({ token, password });
      tokenRef.current = "";
      window.localStorage.setItem(sessionStorageKey, response.token);
      window.dispatchEvent(new Event(sessionChangedEvent));
      setPassword("");
      setVerified(true);
      setNotice(t("notices.verified"));
    } catch (requestError) {
      if (isInvalidVerificationTokenError(requestError)) {
        tokenRef.current = "";
        setNeedsRecovery(true);
      }
      setError(t(emailVerificationErrorMessageKey(requestError)));
    } finally {
      setLoading(false);
    }
  }

  async function resend(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setNotice("");
    setError("");

    if (!email.includes("@")) {
      setError(t("validation.invalidEmail"));
      return;
    }

    setLoading(true);
    try {
      await requestEmailVerification({ email }, { languageTag });
      setNotice(t("notices.resent"));
    } catch (requestError) {
      setError(t(emailVerificationErrorMessageKey(requestError)));
    } finally {
      setLoading(false);
    }
  }

  if (!ready) {
    return (
      <section className="page-section compact auth-page-section">
        <div className="form-panel auth-page-panel" role="status">
          {t("loading")}
        </div>
      </section>
    );
  }

  return (
    <section className="page-section compact auth-page-section">
      <div className="form-panel auth-page-panel">
        {verified ? (
          <div className="form-grid">
            <span className="badge badge-live">
              <BadgeCheck size={12} aria-hidden="true" />
              {t("success.badge")}
            </span>
            <h1 className="result-title">{t("success.title")}</h1>
            <div aria-live="polite">
              <div className="notice">{notice}</div>
            </div>
            <Link className="btn-primary" href="/account">
              {t("actions.openAccount")}
            </Link>
          </div>
        ) : needsRecovery ? (
          <form className="form-grid" onSubmit={resend}>
            <span className="badge badge-running">
              <Mail size={12} aria-hidden="true" />
              {t("recovery.badge")}
            </span>
            <h1 className="result-title">{t("recovery.title")}</h1>
            <p className="card-copy">{t("recovery.description")}</p>
            <div aria-live="polite">
              {notice ? <div className="notice">{notice}</div> : null}
              {error ? <div className="notice error">{error}</div> : null}
            </div>
            <label className="field-label">
              {t("fields.emailLabel")}
              <input
                className="input"
                type="email"
                autoComplete="email"
                placeholder="user@example.com"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
              />
            </label>
            <button className="btn-primary" type="submit" disabled={loading}>
              {t("actions.resend")}
              <ArrowRight size={15} aria-hidden="true" />
            </button>
            <Link className="btn-secondary" href="/auth-checkout">
              {t("actions.backToSignIn")}
            </Link>
          </form>
        ) : (
          <form className="form-grid" onSubmit={verify}>
            <span className="badge badge-running">
              <BadgeCheck size={12} aria-hidden="true" />
              {t("confirm.badge")}
            </span>
            <h1 className="result-title">{t("confirm.title")}</h1>
            <p className="card-copy">{t("confirm.description")}</p>
            <div aria-live="polite">
              {error ? <div className="notice error">{error}</div> : null}
            </div>
            <label className="field-label">
              {t("fields.passwordLabel")}
              <input
                className="input"
                type="password"
                autoComplete="current-password"
                placeholder={t("fields.passwordPlaceholder")}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            </label>
            <button className="btn-primary" type="submit" disabled={loading}>
              {t("actions.verify")}
              <ArrowRight size={15} aria-hidden="true" />
            </button>
          </form>
        )}
      </div>
    </section>
  );
}
