"use client";

import { useState } from "react";
import { MailCheck } from "lucide-react";
import { useTranslations } from "next-intl";
import {
  ApiError,
  apiErrorCode,
  requestEmailVerification,
  sessionChangedEvent,
  sessionStorageKey
} from "@/shared/api/auth";
import { transportErrorMessageKey } from "./transport-error";

export function EmailVerificationPending({
  languageTag
}: {
  languageTag: string;
}) {
  const t = useTranslations("EmailVerification");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function resend() {
    const sessionToken = window.localStorage.getItem(sessionStorageKey);
    setNotice("");
    setError("");

    if (!sessionToken) {
      setError(t("errors.signInRequired"));
      return;
    }

    setLoading(true);
    try {
      await requestEmailVerification(sessionToken, languageTag);
      if (window.localStorage.getItem(sessionStorageKey) !== sessionToken) {
        return;
      }
      setNotice(t("pending.accepted"));
    } catch (requestError) {
      if (window.localStorage.getItem(sessionStorageKey) !== sessionToken) {
        return;
      }
      if (requestError instanceof ApiError && requestError.status === 401) {
        window.localStorage.removeItem(sessionStorageKey);
        window.dispatchEvent(new Event(sessionChangedEvent));
        setError(t("errors.signInRequired"));
      } else if (
        requestError instanceof ApiError &&
        requestError.status === 500 &&
        apiErrorCode(requestError) === "internal_server_error"
      ) {
        setError(t("errors.internalServer"));
      } else {
        setError(t(transportErrorMessageKey(requestError)));
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="form-grid email-verification-pending">
      <span className="badge badge-running">
        <MailCheck size={12} aria-hidden="true" />
        {t("pending.badge")}
      </span>
      <h2>{t("pending.title")}</h2>
      <p className="card-copy">{t("pending.description")}</p>
      <div aria-live="polite">
        {notice ? <div className="notice">{notice}</div> : null}
        {error ? <div className="notice error">{error}</div> : null}
      </div>
      <button
        className="btn-secondary"
        type="button"
        disabled={loading}
        onClick={() => void resend()}
      >
        {loading ? t("pending.resending") : t("pending.resend")}
      </button>
    </div>
  );
}
