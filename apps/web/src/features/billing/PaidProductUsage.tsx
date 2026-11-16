"use client";

import { useTranslations } from "next-intl";
import { PaidReadStatus } from "./use-paid-read";
import { useIntlLocale } from "@/i18n/use-formatting-locale";
import type { usePaidUsage } from "./use-paid-usage";

export function PaidProductUsage({ productId, usage }: { productId: string; usage: ReturnType<typeof usePaidUsage> }) {
  const t = useTranslations("Account.products.usage");
  const paid = useTranslations("Account.products.paid");
  const locale = useIntlLocale();
  const number = new Intl.NumberFormat(locale);
  const { state } = usage;
  if (state.status === PaidReadStatus.Loading) return <p className="card-copy" role="status">{t("loading")}</p>;
  const items = state.status === PaidReadStatus.Ready ? state.data.items.filter((item) => item.product_id === productId) : [];
  if (!items.length) return <p className="card-copy">{paid("usageUnavailable")}</p>;
  return <div className="paid-product-usage">
    {items.map((item) => <section key={item.allowance_id} aria-label={t(item.classification)}>
      <p>{t(item.classification)}</p>
      <p className="card-copy">{item.metric_key} · {item.unit}</p>
      {item.classification === "historical" && <p>{paid("quantity", { quantity: item.quantity, unit: item.unit })}</p>}
      {item.status === "observed" ? <>
        <dl className="paid-usage-values">
          <div><dt>{t("used")}</dt><dd>{number.format(item.successful_used)}</dd></div>
          <div><dt>{t("reserved")}</dt><dd>{number.format(item.reserved)}</dd></div>
          <div><dt>{t("remaining")}</dt><dd>{number.format(item.remaining)}</dd></div>
          <div><dt>{t("available")}</dt><dd>{number.format(item.available)}</dd></div>
        </dl>
        {item.remaining === 0 ? <p>{t("exhausted")}</p> : item.available === 0 ? <p>{t("busy")}</p> : null}
        <p className="card-copy">{t("readAt", { time: new Intl.DateTimeFormat(locale, { dateStyle: "short", timeStyle: "medium", timeZone: "UTC" }).format(new Date(item.read_at)) })}</p>
      </> : <p className="card-copy">{item.status === "unobserved" ? t("unobserved") : paid("usageUnavailable")}</p>}
    </section>)}
  </div>;
}
