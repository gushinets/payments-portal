import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { ArrowLeft, ArrowRight } from "lucide-react";
import { getTranslations } from "next-intl/server";

import { productPresentation } from "@/features/catalog";
import { getCurrentRouteLocale } from "@/i18n/current-locale";
import { createLocalizedMetadata } from "@/i18n/metadata";
import { Link } from "@/i18n/navigation";

type ProductPageProps = Readonly<{
  params: Promise<{ locale: string; product: string }>;
}>;

function getProduct(slug: string) {
  const product = productPresentation.find((item) => item.slug === slug);

  if (!product) {
    notFound();
  }

  return product;
}

export const dynamicParams = false;

export function generateStaticParams() {
  return productPresentation.map(({ slug }) => ({ product: slug }));
}

export async function generateMetadata({
  params
}: ProductPageProps): Promise<Metadata> {
  const [{ product: productSlug }, routeLocale] = await Promise.all([
    params,
    getCurrentRouteLocale()
  ]);
  const product = getProduct(productSlug);

  return createLocalizedMetadata(
    routeLocale,
    `/products/${product.slug}`
  );
}

export default async function ProductDetailPage({
  params
}: ProductPageProps) {
  const [{ product: productSlug }, t] = await Promise.all([
    params,
    getTranslations("Catalog")
  ]);
  const product = getProduct(productSlug);
  const Icon = product.Icon;

  return (
    <section className="page-section compact">
      <Link className="nav-link product-back-link" href="/products">
        <ArrowLeft size={15} aria-hidden="true" />
        {t("backToCatalog")}
      </Link>
      <article className="product-detail-card">
        <div className="tool-icon-wrap">
          <Icon size={22} aria-hidden="true" />
        </div>
        <span className="tool-tag">
          {t(`products.${product.messageKey}.type`)}
        </span>
        <h1 className="legal-title">
          {t(`products.${product.messageKey}.tagline`)}
        </h1>
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
      </article>
    </section>
  );
}
