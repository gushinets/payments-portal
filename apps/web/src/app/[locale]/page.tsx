import type { Metadata } from "next";
import { ArrowRight, Sparkles } from "lucide-react";
import { getTranslations } from "next-intl/server";
import {
  ProductOverview,
  productPresentation
} from "@/features/catalog";
import { getCurrentRouteLocale } from "@/i18n/current-locale";
import { createLocalizedMetadata } from "@/i18n/metadata";
import { Link } from "@/i18n/navigation";

export async function generateMetadata(): Promise<Metadata> {
  return createLocalizedMetadata(await getCurrentRouteLocale(), "/");
}

export default async function HomePage() {
  const [t, catalog] = await Promise.all([
    getTranslations("Home"),
    getTranslations("Catalog")
  ]);

  return (
    <>
      <section className="page-section public-home-hero">
        <div className="public-hero">
          <div className="eyebrow">{t("eyebrow")}</div>
          <h1 className="hero-h1">
            {t.rich("hero.heading", {
              em: (chunks) => <em className="h1-grad">{chunks}</em>
            })}
          </h1>
          <p className="hero-copy">{t("hero.description")}</p>
          <div className="hero-actions">
            <Link className="btn-primary" href="/account">
              {t("hero.primaryAction")}
              <ArrowRight size={16} aria-hidden="true" />
            </Link>
            <Link className="btn-secondary" href="#products">
              {t("hero.secondaryAction")}
            </Link>
          </div>
        </div>
      </section>

      <section className="page-section product-discovery" id="products">
        <div className="product-collection">
          <div className="collection-icon" aria-hidden="true">
            <Sparkles size={24} />
          </div>
          <div className="collection-content">
            <div className="collection-label">{t("products.eyebrow")}</div>
            <h2 className="section-title">{t("products.title")}</h2>
            <p className="section-copy">{t("products.description")}</p>
            <ul className="collection-products">
              {productPresentation.map((product) => (
                <li key={product.slug}>
                  {catalog(`products.${product.messageKey}.name`)}
                </li>
              ))}
            </ul>
          </div>
          <Link className="btn-secondary collection-action" href="/products">
            {t("products.action")}
            <ArrowRight size={16} aria-hidden="true" />
          </Link>
        </div>
        <ProductOverview />
      </section>
    </>
  );
}
