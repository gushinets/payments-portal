"use client";

import { useTranslations } from "next-intl";
import { useBillingWidget } from "./use-billing-widget";
import { WidgetView } from "./WidgetView";

export function BillingAccount({ userId, emailVerified }: { userId: string; emailVerified: boolean }) {
  const t = useTranslations("Billing");
  const widget = useBillingWidget(userId, emailVerified);
  return (
    <section className="account-products-panel" aria-label={t("title")}>
      <h2>{t("title")}</h2>
      <p className="card-copy">{t("description")}</p>
      {!emailVerified && <p className="card-copy">{t("verificationRequired")}</p>}
      <button className="btn-secondary" type="button" disabled={!emailVerified || widget.state.status === "loading"} onClick={() => void widget.open()}>
        {widget.state.status === "loading" ? t("loading") : t("open")}
      </button>
      <WidgetView widget={widget} />
    </section>
  );
}
