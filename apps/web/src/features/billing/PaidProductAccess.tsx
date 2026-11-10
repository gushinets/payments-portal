"use client";

import { useTranslations } from "next-intl";
import type { usePaidAccess } from "./use-paid-access";
import { kernelLaunchUrl } from "@/shared/config/kernel-web";

export function PaidProductAccess({ productId, paid }: { productId: string; paid: ReturnType<typeof usePaidAccess> }) {
  const t = useTranslations("Account.products.paid");
  const { state } = paid;
  if (state.status === "loading") return <p className="card-copy" role="status">{t("loading")}</p>;
  const data = state.status === "ready" ? state.data : null;
  const evidence = data?.products.find((item) => item.product_id === productId);
  const granted = data?.grants.some((item) => item.product_id === productId);
  const status = granted ? "confirmed" : evidence?.status ?? "unavailable";
  const allowances = data?.allowances.filter((item) => item.product_id === productId) ?? [];
  const launchUrl = granted ? kernelLaunchUrl(productId) : null;
  return <div className="paid-product-access">
    <p>{t(status)}</p>
    {granted && <>
      {allowances.map((item) => <div key={item.allowance_id}>
        <p>{t("quantity", { quantity: item.quantity, unit: item.unit })}</p>
        <p className="card-copy">{item.metric_key}</p>
        {item.provenance === "SIMULATED" && <p className="card-copy">{t("simulated")}</p>}
      </div>)}
      {!allowances.length && <p className="card-copy">{t("meteringUnavailable")}</p>}
      {launchUrl ? <a className="btn-primary" href={launchUrl} referrerPolicy="no-referrer">{t("openProduct")}</a> : <p className="card-copy">{t("launchUnavailable")}</p>}
    </>}
    <p className="card-copy">{t("usageUnavailable")}</p>
  </div>;
}
