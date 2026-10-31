"use client";

import { useTranslations } from "next-intl";
import type { useBillingWidget } from "./use-billing-widget";

export function WidgetView({ widget, onClose }: { widget: ReturnType<typeof useBillingWidget>; onClose?: () => void }) {
  const t = useTranslations("Billing");
  const { state, attachNode, close } = widget;
  return <div className="billing-widget">
    {state.status !== "closed" && <button className="btn-secondary" type="button" onClick={() => { close(); onClose?.(); }}>{t("close")}</button>}
    <div aria-live="polite">
      {state.status === "loading" && <p role="status">{t("loading")}</p>}
      {state.status === "error" && <div className="notice error" role="alert">
        {t(`errors.${state.message}`)}
        {state.requestId && <p>{t("requestId", { id: state.requestId })}</p>}
      </div>}
      {state.status === "open" && state.target && <div className="notice">
        <p>{t("paymentTarget", { agreement: state.target.agreement_reference, seller: state.target.seller_reference })}</p>
        <p>{t("paymentTargetNote")}</p>
      </div>}
    </div>
    <div ref={attachNode} hidden={state.status !== "open"} />
  </div>;
}
