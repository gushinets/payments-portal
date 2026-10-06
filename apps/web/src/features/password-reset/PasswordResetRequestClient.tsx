"use client";

import { type FormEvent, useState } from "react";
import { ArrowRight, Mail } from "lucide-react";
import { useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";
import { requestPasswordReset } from "@/shared/api/auth";
import { passwordResetErrorMessageKey } from "./errors";

export function PasswordResetRequestClient({
  languageTag
}: {
  languageTag: string;
}) {
  const t = useTranslations("PasswordReset");
  const [email, setEmail] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setNotice("");
    setError("");

    if (!email.includes("@")) {
      setError(t("request.validation.invalidEmail"));
      return;
    }

    setLoading(true);
    try {
      await requestPasswordReset({ email }, { languageTag });
      setNotice(t("request.notices.accepted"));
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
            <Mail size={12} aria-hidden="true" />
            {t("request.badge")}
          </span>
          <h1 className="result-title">{t("request.title")}</h1>
          <p className="card-copy">{t("request.description")}</p>

          <div aria-live="polite">
            {notice ? <div className="notice">{notice}</div> : null}
            {error ? <div className="notice error">{error}</div> : null}
          </div>

          <label className="field-label">
            {t("request.fields.emailLabel")}
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
            {t("request.actions.submit")}
            <ArrowRight size={15} aria-hidden="true" />
          </button>

          <Link className="btn-secondary" href="/account">
            {t("request.actions.backToSignIn")}
          </Link>
        </form>
      </div>
    </section>
  );
}
