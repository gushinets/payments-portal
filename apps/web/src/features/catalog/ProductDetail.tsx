import { ArrowLeft } from "lucide-react";
import { getTranslations } from "next-intl/server";

import { Link } from "@/i18n/navigation";

import { CatalogPreview } from "./CatalogPreview";

export async function ProductDetail({ productId }: { productId: string }) {
  const t = await getTranslations("Catalog");
  const preview = await getTranslations("CatalogPreview");
  return (
    <article className="page-section compact product-detail">
      <Link className="nav-link product-back-link" href="/products">
        <ArrowLeft size={15} aria-hidden="true" />{t("backToCatalog")}
      </Link>
      <div className="product-hero">
        <div className="product-hero-content">
          <p className="product-eyebrow">{t("page.title")}</p>
          <h1 className="section-title product-detail-title">{preview("productTitle")}</h1>
          <p className="catalog-product-id">{productId}</p>
          <p className="hero-copy">{preview("fallback")}</p>
          <Link className="btn-secondary" href="/account">{t("signInAction")}</Link>
          <p className="product-action-note">{t("detail.accountNote")}</p>
        </div>
        <CatalogPreview productId={productId} />
      </div>
      <section className="product-readiness" aria-labelledby="product-readiness-title">
        <h2 id="product-readiness-title">{t("detail.readiness.title")}</h2>
        <dl className="product-readiness-grid">
          <div><dt>{t("detail.readiness.access.label")}</dt><dd>{t("detail.readiness.access.description")}</dd></div>
          <div><dt>{t("detail.readiness.usage.label")}</dt><dd>{t("detail.readiness.usage.description")}</dd></div>
        </dl>
      </section>
    </article>
  );
}
