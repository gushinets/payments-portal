"use client";

import { useTranslations } from "next-intl";
import type { PurchaseReviewResponse } from "@/generated/api-contracts/types.gen";
import { useIntlLocale } from "@/i18n/use-formatting-locale";
import { formatCatalogMoney } from "@/shared/formatting/money";

export function PurchaseTerms({ review }: { review: PurchaseReviewResponse }) {
  const t = useTranslations("Purchase");
  const catalog = useTranslations("CatalogPreview");
  const locale = useIntlLocale();
  const terms = review.terms;
  const technical = review.technical_terms;
  return <dl className="approved-offer-terms">
    <div><dt>{catalog("recurring")}</dt><dd>{formatCatalogMoney(terms.recurring_amount, terms.currency, locale)}</dd></div>
    <div><dt>{catalog("connection")}</dt><dd>{formatCatalogMoney(terms.connection_amount, terms.currency, locale)}</dd></div>
    <div><dt>{catalog("period")}</dt><dd>{catalog(`periodUnits.${terms.period_unit}`, { count: terms.period_length })}<br />{catalog(`periodAnchors.${terms.period_anchor}`)}</dd></div>
    <div><dt>{catalog("quantity")}</dt><dd>{terms.commercial_quantity}</dd></div>
    <div><dt>{catalog("terms")}</dt><dd>{catalog(terms.prepaid ? "prepaid" : "paymentUnspecified")}<br />{t(terms.full_funding_required ? "fullFunding" : "fundingUnspecified")}</dd></div>
    <div><dt>{t("technicalLimit")}</dt><dd>{technical ? <><span>{technical.offer.quantity.toLocaleString(locale)} {technical.offer.unit}</span><br /><span>{technical.offer.metric_key}</span><br /><span>{t("simulatedTerms")}</span></> : t("technicalUnknown")}</dd></div>
  </dl>;
}
