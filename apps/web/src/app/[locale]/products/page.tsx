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
    <>
      <section className="page-section compact">
        <div className="eyebrow">
          <span className="eyebrow-dot" />
          {t("page.eyebrow")}
        </div>
        <h1 className="legal-title">{t("page.title")}</h1>
        <p className="hero-copy">{t("page.description")}</p>
        <ProductOverview />
      </section>
    </>
  );
}
