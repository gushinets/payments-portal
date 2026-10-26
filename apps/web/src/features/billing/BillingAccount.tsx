"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { bootstrapWidget } from "@/shared/api/billing";
import { ApiError, apiErrorCode } from "@/shared/api/transport";
import { subscribeToSessionChanges, useSessionOperation } from "@/shared/session/use-session-operation";
import { mountOfficialWidget } from "./official-widget-sdk";

type BillingErrorKey = "session" | "verification" | "identity" | "pending" | "review" | "serverAuth" | "response" | "client" | "configuration" | "unavailable" | "sdk";

type BillingState =
  | { status: "closed" }
  | { status: "loading" }
  | { status: "open" }
  | { status: "error"; message: BillingErrorKey; requestId: string };

function requestId(error: unknown): string {
  if (!(error instanceof ApiError) || typeof error.detail !== "object" || error.detail === null || !("request_id" in error.detail)) return "";
  const id = error.detail.request_id;
  return typeof id === "string" && /^[A-Za-z0-9._-]{1,128}$/.test(id) ? id : "";
}

function errorKey(error: unknown): BillingErrorKey {
  const code = apiErrorCode(error);
  switch (code) {
    case "billing_session_required": return "session";
    case "billing_email_verification_required": return "verification";
    case "billing_connection_conflict":
    case "billing_identity_conflict":
    case "billing_identity_unproven":
    case "billing_legacy_identity_unproven": return "identity";
    case "billing_customer_pending": return "pending";
    case "billing_customer_review": return "review";
    case "billing_server_auth_failed": return "serverAuth";
    case "billing_source_invalid_response": return "response";
    case "billing_client_not_ready": return "client";
    case "lbx_not_configured":
    case "lbx_connection_fields_required":
    case "lbx_base_url_invalid":
    case "lbx_base_url_requires_public_https":
    case "lbx_server_credentials_invalid":
    case "lbx_widget_signing_secret_required": return "configuration";
    default: return "unavailable";
  }
}

export function BillingAccount({ userId, emailVerified }: { userId: string; emailVerified: boolean }) {
  const t = useTranslations("Billing");
  const { begin, cancel } = useSessionOperation();
  const [state, setState] = useState<BillingState>({ status: "closed" });
  const node = useRef<HTMLDivElement>(null);
  const dispose = useRef<(() => void) | undefined>(undefined);
  const opening = useRef(false);

  useEffect(() => {
    const clear = () => {
      cancel();
      dispose.current?.();
      dispose.current = undefined;
      opening.current = false;
      setState({ status: "closed" });
    };
    const unsubscribe = subscribeToSessionChanges(clear);
    return () => {
      unsubscribe();
      cancel();
      dispose.current?.();
      dispose.current = undefined;
      opening.current = false;
    };
  }, [userId, emailVerified, cancel]);

  async function open() {
    if (!emailVerified || opening.current) return;
    opening.current = true;
    dispose.current?.();
    dispose.current = undefined;
    const operation = begin();
    const correlationId = Array.from(window.crypto.getRandomValues(new Uint8Array(16)), (value) => value.toString(16).padStart(2, "0")).join("");
    setState({ status: "loading" });
    try {
      if (!operation.token) {
        setState({ status: "error", message: "session", requestId: "" });
        return;
      }
      const response = await bootstrapWidget(operation.token, correlationId);
      if (!operation.isCurrent() || !node.current) {
        response.credential = "";
        return;
      }
      const id = response.request_id || correlationId;
      const sdkFailure = () => {
        if (operation.isCurrent()) setState({ status: "error", message: "sdk", requestId: id });
      };
      try {
        dispose.current = mountOfficialWidget(node.current, response, t("frameTitle"), operation.isCurrent, sdkFailure);
        setState({ status: "open" });
      } catch {
        response.credential = "";
        sdkFailure();
      }
    } catch (error) {
      if (operation.isCurrent()) setState({ status: "error", message: errorKey(error), requestId: requestId(error) || correlationId });
    } finally {
      if (operation.isLatest()) opening.current = false;
    }
  }

  function close() {
    cancel();
    dispose.current?.();
    dispose.current = undefined;
    opening.current = false;
    setState({ status: "closed" });
  }

  return (
    <section className="account-products-panel" aria-label={t("title")}>
      <h2>{t("title")}</h2>
      <p className="card-copy">{t("description")}</p>
      {!emailVerified ? <p className="card-copy">{t("verificationRequired")}</p> : null}
      <button className="btn-secondary" type="button" disabled={!emailVerified || state.status === "loading"} onClick={() => void open()}>
        {state.status === "loading" ? t("loading") : t("open")}
      </button>
      {state.status !== "closed" ? <button className="btn-secondary" type="button" onClick={close}>{t("close")}</button> : null}
      <div aria-live="polite">
        {state.status === "error" ? <div className="notice error" role="alert">
          {t(`errors.${state.message}`)}
          {state.requestId ? <p>{t("requestId", { id: state.requestId })}</p> : null}
        </div> : null}
      </div>
      <div ref={node} hidden={state.status !== "open"} />
    </section>
  );
}
