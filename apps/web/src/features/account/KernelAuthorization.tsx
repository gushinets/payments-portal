"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { createKernelSessionCode } from "@/shared/api/kernel-session";
import { kernelWebBaseUrl, parseKernelAuthorizationQuery } from "@/shared/config/kernel-web";
import { subscribeToSessionChanges, useSessionOperation } from "@/shared/session/use-session-operation";

export function KernelAuthorization({ navigate = (url: string) => window.location.replace(url) }: { navigate?: (url: string) => void }) {
  const t = useTranslations("KernelSession");
  const { begin, cancel } = useSessionOperation();
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  useEffect(() => subscribeToSessionChanges(() => { cancel(); setBusy(false); setFailed(false); }), [cancel]);

  async function authorize() {
    const operation = begin();
    const query = parseKernelAuthorizationQuery(new URLSearchParams(window.location.search));
    const base = kernelWebBaseUrl();
    if (!operation.token || !query || !base) { setFailed(true); return; }
    setBusy(true);
    setFailed(false);
    try {
      const response = await createKernelSessionCode(operation.token, query.challenge);
      if (!operation.isCurrent()) return;
      // The destination is deployment-owned. No caller-selected callback or Portal bearer leaves this app.
      const callback = new URL(`${base}/portal-session/callback`);
      callback.hash = new URLSearchParams({ code: response.code, state: query.state }).toString();
      navigate(callback.href);
    } catch {
      if (operation.isCurrent()) setFailed(true);
    } finally {
      if (operation.isLatest()) setBusy(false);
    }
  }

  return <section className="account-products-panel" aria-labelledby="kernel-authorization-title">
    <h2 id="kernel-authorization-title">{t("title")}</h2>
    <p className="card-copy">{t("description")}</p>
    <button className="btn-primary" type="button" disabled={busy} onClick={() => void authorize()}>{t(busy ? "loading" : "continue")}</button>
    {failed && <p className="notice error" role="alert">{t("failed")}</p>}
  </section>;
}
