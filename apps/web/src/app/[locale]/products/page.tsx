import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { ProductOverview } from "@/features/catalog";
import { getCurrentRouteLocale } from "@/i18n/current-locale";
import { createLocalizedMetadata } from "@/i18n/metadata";

export async function generateMetadata(): Promise<Metadata> {
  return createLocalizedMetadata(await getCurrentRouteLocale(), "/products");
}

export default async function ProductsPage() {
  const t = await getTranslations("Catalog");

  return (
    <section className="page-section compact catalog-page">
      <div className="catalog-heading">
        <div className="eyebrow">{t("page.eyebrow")}</div>
        <h1 className="section-title catalog-title">{t("page.title")}</h1>
        <p className="hero-copy">{t("page.description")}</p>
      </div>
      <ProductOverview headingLevel={2} />
    </section>
  );
}
