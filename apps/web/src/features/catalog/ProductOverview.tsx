import { ArrowRight } from "lucide-react";
import { getTranslations } from "next-intl/server";
import { Link } from "@/i18n/navigation";
import { productPresentation } from "./catalog";

export async function ProductOverview({
  headingLevel = 3
}: {
  headingLevel?: 2 | 3;
}) {
  const t = await getTranslations("Catalog");
  const ProductHeading = headingLevel === 2 ? "h2" : "h3";

  return (
    <div className="tools-grid">
      {productPresentation.map((product) => {
        const Icon = product.Icon;
        return (
          <Link
            className="tool-card"
            href={`/products/${product.slug}`}
            key={product.slug}
          >
            <div className="tool-card-top">
              <div className="tool-icon-wrap">
                <Icon size={22} aria-hidden="true" />
              </div>
              <span className="tool-tag tool-card-type">
                {t(`products.${product.messageKey}.type`)}
              </span>
            </div>
            <ProductHeading>
              {t(`products.${product.messageKey}.name`)}
            </ProductHeading>
            <p className="tool-card-tagline">
              {t(`products.${product.messageKey}.tagline`)}
            </p>
            <p className="card-copy">
              {t(`products.${product.messageKey}.description`)}
            </p>
            <div className="tool-card-bottom">
              <span className="tool-detail-action">
                {t("detailsAction")}
                <ArrowRight size={15} aria-hidden="true" />
              </span>
            </div>
          </Link>
        );
      })}
    </div>
  );
}
