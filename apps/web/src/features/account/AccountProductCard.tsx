"use client";

import { ArrowRight } from "lucide-react";
import { useTranslations } from "next-intl";
import type { ProductPresentation } from "@/features/catalog";
import { Link } from "@/i18n/navigation";

// Presentation slots only; missing data does not describe a business outcome.
const statusSlots = ["commercial", "access", "usage"] as const;

export function AccountProductCard({
  product
}: {
  product: ProductPresentation;
}) {
  const t = useTranslations("Account.products");
  const catalogT = useTranslations("Catalog.products");
  const Icon = product.Icon;
  const titleId = `account-product-${product.slug}`;
  const actionId = `${titleId}-action`;

  return (
    <article
      className="form-panel account-product-card"
      aria-labelledby={titleId}
    >
      <header className="account-product-heading">
        <div className="tool-icon-wrap">
          <Icon size={22} aria-hidden="true" />
        </div>
        <div>
          <span className="tool-tag">
            {catalogT(`${product.messageKey}.type`)}
          </span>
          <h3 id={titleId}>{catalogT(`${product.messageKey}.name`)}</h3>
        </div>
      </header>
      <p className="card-copy account-product-description">
        {catalogT(`${product.messageKey}.tagline`)}
      </p>

      <dl className="account-product-statuses">
        {statusSlots.map((slot) => (
          <div className="account-product-status" key={slot}>
            <dt>{t(`state.${slot}.label`)}</dt>
            <dd>{t(`state.${slot}.description`)}</dd>
          </div>
        ))}
      </dl>

      <footer className="account-product-actions">
        <p className="card-copy">{t("action.description")}</p>
        <Link
          className="btn-secondary"
          href={`/products/${product.slug}`}
          aria-labelledby={`${actionId} ${titleId}`}
        >
          <span id={actionId}>{t("detailAction")}</span>
          <ArrowRight size={15} aria-hidden="true" />
        </Link>
      </footer>
    </article>
  );
}
