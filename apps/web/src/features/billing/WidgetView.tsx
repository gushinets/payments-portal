"use client";

import { useTranslations } from "next-intl";
import { WidgetStatus, type useBillingWidget } from "./use-billing-widget";

export function WidgetView({ widget, onClose }: { widget: ReturnType<typeof useBillingWidget>; onClose?: () => void }) {
  const t = useTranslations("Billing");
  const { state, loading, attachNode, close } = widget;
  const mounted = state.status === WidgetStatus.Rendering || state.status === WidgetStatus.Open;
  return <div className="billing-widget">
    {state.status !== WidgetStatus.Closed && <button className="btn-secondary" type="button" onClick={() => { close(); onClose?.(); }}>{t("close")}</button>}
    <div aria-live="polite">
      {loading && <p role="status">{t("loading")}</p>}
      {state.status === WidgetStatus.Error && <div className="notice error" role="alert">
        {t(`errors.${state.message}`)}
        {state.requestId && <p>{t("requestId", { id: state.requestId })}</p>}
      </div>}
    </div>
    <div ref={attachNode} hidden={!mounted} className={state.status === WidgetStatus.Rendering ? "billing-widget-rendering" : undefined} />
  </div>;
}
