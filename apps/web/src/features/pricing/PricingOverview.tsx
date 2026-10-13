import { ArrowLeft, ArrowRight } from "lucide-react";
import { getTranslations } from "next-intl/server";

import { Link } from "@/i18n/navigation";

export async function PricingOverview() {
  const t = await getTranslations("Pricing");

  return (
    <section className="page-section compact pricing-page">
      <Link className="nav-link pricing-back-link" href="/">
        <ArrowLeft size={15} aria-hidden="true" />
        {t("backAction")}
      </Link>
      <header className="pricing-heading">
        <h1 className="section-title">{t("title")}</h1>
        <p className="hero-copy">{t("description")}</p>
      </header>
      <article
        className="pricing-placeholder"
        aria-labelledby="pricing-placeholder-title"
      >
        <span className="badge badge-demo">{t("placeholder.badge")}</span>
        <h2 id="pricing-placeholder-title">{t("placeholder.title")}</h2>
        <p className="card-copy">{t("placeholder.description")}</p>
        <Link className="btn-secondary" href="/products">
          {t("productsAction")}
          <ArrowRight size={15} aria-hidden="true" />
        </Link>
      </article>
    </section>
  );
}
