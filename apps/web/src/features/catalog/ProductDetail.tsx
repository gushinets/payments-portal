import { ArrowLeft } from "lucide-react";
import { NextIntlClientProvider } from "next-intl";
import { getMessages, getTranslations } from "next-intl/server";

import { Link } from "@/i18n/navigation";
import { ProductDetailContent } from "./ProductDetailContent";

export async function ProductDetail({ productId }: { productId: string }) {
  const t = await getTranslations("Catalog");
  const preview = await getTranslations("CatalogPreview");
  const messages = await getMessages();
  return (
    <article className="page-section compact product-detail">
      <Link className="nav-link product-back-link" href="/products">
        <ArrowLeft size={15} aria-hidden="true" />{t("backToCatalog")}
      </Link>
      <NextIntlClientProvider messages={{ Billing: messages.Billing, Purchase: messages.Purchase, CatalogPreview: messages.CatalogPreview }}>
        <ProductDetailContent key={productId} productId={productId}>
          <p className="product-eyebrow">{t("page.title")}</p>
          <h1 className="section-title product-detail-title">{preview("productTitle")}</h1>
          <p className="catalog-product-id">{productId}</p>
          <p className="hero-copy">{preview("fallback")}</p>
        </ProductDetailContent>
      </NextIntlClientProvider>
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
