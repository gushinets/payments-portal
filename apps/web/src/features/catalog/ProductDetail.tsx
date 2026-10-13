import { ArrowLeft, ArrowRight } from "lucide-react";
import { getTranslations } from "next-intl/server";

import { Link } from "@/i18n/navigation";

import type { ProductPresentation } from "./catalog";

export async function ProductDetail({
  product
}: {
  product: ProductPresentation;
}) {
  const t = await getTranslations("Catalog");
  const Icon = product.Icon;
  const PreviewIcon = product.PreviewIcon;

  return (
    <article className="page-section compact product-detail">
      <Link className="nav-link product-back-link" href="/products">
        <ArrowLeft size={15} aria-hidden="true" />
        {t("backToCatalog")}
      </Link>

      <div className="product-hero">
        <div className="product-hero-content">
          <p className="product-eyebrow">
            <span>{t("page.title")}</span>
            <span aria-hidden="true">·</span>
            <span>{t(`products.${product.messageKey}.type`)}</span>
          </p>
          <h1 className="section-title product-detail-title">
            {t(`products.${product.messageKey}.name`)}
          </h1>
          <p className="product-value">
            {t(`products.${product.messageKey}.tagline`)}
          </p>
          <p className="hero-copy">
            {t(`products.${product.messageKey}.description`)}
          </p>
          <div className="hero-actions">
            <Link className="btn-primary" href="/account">
              {t("signInAction")}
              <ArrowRight size={16} aria-hidden="true" />
            </Link>
            <Link className="btn-secondary" href="/products">
              {t("backToCatalog")}
            </Link>
          </div>
          <p className="product-action-note">{t("detail.accountNote")}</p>
        </div>

        <figure className={`product-preview product-preview-${product.slug}`}>
          <p className="product-preview-label">{t("detail.previewLabel")}</p>
          <div className="product-illustration" aria-hidden="true">
            <div className="product-illustration-source">
              <Icon size={32} />
              <div className="product-illustration-lines">
                <span />
                <span />
                <span />
                <span />
              </div>
            </div>
            <ArrowRight className="product-illustration-arrow" size={24} />
            <div className="product-illustration-focus">
              <PreviewIcon size={40} />
              <div className="product-illustration-lines">
                <span />
                <span />
                <span />
              </div>
            </div>
          </div>
          <figcaption className="product-preview-caption">
            <strong>{t(`products.${product.messageKey}.detail.previewCaption`)}</strong>
            <span>{t("detail.previewNote")}</span>
          </figcaption>
        </figure>
      </div>

      <section className="product-information" aria-labelledby="product-information-title">
        <h2 className="section-title" id="product-information-title">
          {t("detail.informationTitle")}
        </h2>
        <div className="product-information-grid">
          {product.highlights.map((highlight) => {
            const HighlightIcon = highlight.Icon;

            return (
              <div className="product-info-card" key={highlight.messageKey}>
                <div className="tool-icon-wrap">
                  <HighlightIcon size={22} aria-hidden="true" />
                </div>
                <h3>
                  {t(`products.${product.messageKey}.detail.${highlight.messageKey}.title`)}
                </h3>
                <p className="card-copy">
                  {t(`products.${product.messageKey}.detail.${highlight.messageKey}.description`)}
                </p>
              </div>
            );
          })}
        </div>
      </section>

      <section className="product-readiness" aria-labelledby="product-readiness-title">
        <h2 id="product-readiness-title">{t("detail.readiness.title")}</h2>
        <dl className="product-readiness-grid">
          <div>
            <dt>{t("detail.readiness.commercial.label")}</dt>
            <dd>{t("detail.readiness.commercial.description")}</dd>
          </div>
          <div>
            <dt>{t("detail.readiness.access.label")}</dt>
            <dd>{t("detail.readiness.access.description")}</dd>
          </div>
          <div>
            <dt>{t("detail.readiness.usage.label")}</dt>
            <dd>{t("detail.readiness.usage.description")}</dd>
          </div>
        </dl>
      </section>
    </article>
  );
}
