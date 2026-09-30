import { ArrowRight } from "lucide-react";
import { getTranslations } from "next-intl/server";
import { Link } from "@/i18n/navigation";
import { productPresentation } from "./catalog";

export async function ProductOverview() {
  const t = await getTranslations("Catalog");

  return (
    <>
      <div className="notice" role="status" style={{ marginBottom: 16 }}>
        {t("availabilityNotice")}
      </div>
      <div className="tools-grid">
        {productPresentation.map((product) => {
          const Icon = product.Icon;
          return (
            <article className="tool-card" key={product.code}>
              <div className="tool-icon-wrap">
                <Icon size={22} aria-hidden="true" />
              </div>
              <span className="tool-tag">
                {t(`products.${product.messageKey}.type`)}
              </span>
              <h3>{t(`products.${product.messageKey}.tagline`)}</h3>
              <p className="card-copy">
                {t(`products.${product.messageKey}.description`)}
              </p>
              <div className="tool-card-bottom">
                <span className="badge badge-demo">{t("productInfoBadge")}</span>
              </div>
            </article>
          );
        })}
      </div>
      <div className="hero-actions">
        <Link className="btn-primary" href="/auth-checkout">
          {t("signInAction")}
          <ArrowRight size={15} aria-hidden="true" />
        </Link>
      </div>
    </>
  );
}
