import type { Metadata } from "next";
import { ArrowRight } from "lucide-react";
import { getTranslations } from "next-intl/server";
import {
  catalogRegion,
  legalDocumentLanguage,
  ProductOverview,
  platformFacts,
  platformHighlights
} from "@/features/catalog";
import { SUPPORTED_ROUTE_LOCALES } from "@/generated/locales";
import { getCurrentRouteLocale } from "@/i18n/current-locale";
import { createLocalizedMetadata } from "@/i18n/metadata";
import { Link } from "@/i18n/navigation";

export async function generateMetadata(): Promise<Metadata> {
  return createLocalizedMetadata(await getCurrentRouteLocale(), "/");
}

export default async function HomePage() {
  const t = await getTranslations("Home");

  return (
    <>
      <section className="page-section">
        <div className="bento-grid">
          <article className="hero-card">
            <div>
              <div className="eyebrow">
                <span className="eyebrow-dot" />
                {t("eyebrow", { region: catalogRegion })}
              </div>
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
            <aside className="hero-aside" aria-label={t("factsAriaLabel")}>
              <div className="stats-grid">
                {platformFacts.map((fact) => {
                  const Icon = fact.Icon;
                  const values = {
                    legalLanguage: legalDocumentLanguage,
                    localeCount: SUPPORTED_ROUTE_LOCALES.length,
                    region: catalogRegion
                  };

                  return (
                    <div className="stat-cell" key={fact.messageKey}>
                      <Icon className="stat-icon" aria-hidden="true" />
                      <div className="stat-val">
                        {t(`facts.${fact.messageKey}.value`, values)}
                      </div>
                      <div className="stat-lbl">
                        {t(`facts.${fact.messageKey}.label`)}
                      </div>
                      <div className="muted">
                        {t(`facts.${fact.messageKey}.detail`, values)}
                      </div>
                    </div>
                  );
                })}
              </div>
            </aside>
          </article>

          {platformHighlights.map((item) => {
            const Icon = item.Icon;

            return (
              <article className="feature-card" key={item.messageKey}>
                <Icon className="stat-icon" aria-hidden="true" />
                <strong>{t(`highlights.${item.messageKey}.title`)}</strong>
                <p className="card-copy">
                  {t(`highlights.${item.messageKey}.description`)}
                </p>
              </article>
            );
          })}
        </div>
      </section>

      <section className="page-section compact" id="products">
        <div className="eyebrow">
          <span className="eyebrow-dot" />
          {t("products.eyebrow")}
        </div>
        <h2 className="section-title">{t("products.title")}</h2>
        <p className="section-copy">{t("products.description")}</p>
        <ProductOverview />
      </section>
    </>
  );
}
