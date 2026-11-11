"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { createBackendSessionCode } from "@/shared/api/backend-session";
import { parseBackendAuthorizationQuery, type BackendCallback } from "@/shared/config/backend-authorization";
import { subscribeToSessionChanges, useSessionOperation } from "@/shared/session/use-session-operation";

export function BackendAuthorization({ callbacks, navigate = (url: string) => window.location.replace(url) }: { callbacks: BackendCallback[]; navigate?: (url: string) => void }) {
  const t = useTranslations("BackendSession");
  const { begin, cancel } = useSessionOperation();
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  useEffect(() => subscribeToSessionChanges(() => { cancel(); setBusy(false); setFailed(false); }), [cancel]);

  async function authorize() {
    const operation = begin();
    const query = parseBackendAuthorizationQuery(new URLSearchParams(window.location.search));
    const destination = callbacks.find((entry) => entry.consumerId === query?.consumerId);
    if (!operation.token || !query || !destination) { setFailed(true); return; }
    setBusy(true);
    setFailed(false);
    try {
      const response = await createBackendSessionCode(operation.token, query.consumerId, query.challenge);
      if (!operation.isCurrent()) return;
      // The destination is deployment-owned. No caller-selected callback or Portal bearer leaves this app.
      const callback = new URL(destination.callbackUrl);
      callback.hash = new URLSearchParams({ code: response.code, state: query.state }).toString();
      navigate(callback.href);
    } catch {
      if (operation.isCurrent()) setFailed(true);
    } finally {
      if (operation.isLatest()) setBusy(false);
    }
  }

  return <section className="account-products-panel" aria-labelledby="backend-authorization-title">
    <h2 id="backend-authorization-title">{t("title")}</h2>
    <p className="card-copy">{t("description")}</p>
    <button className="btn-primary" type="button" disabled={busy} onClick={() => void authorize()}>{t(busy ? "loading" : "continue")}</button>
    {failed && <p className="notice error" role="alert">{t("failed")}</p>}
  </section>;
}
