"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import type { CatalogProductResponse } from "@/generated/api-contracts/types.gen";
import { Link } from "@/i18n/navigation";
import { useIntlLocale } from "@/i18n/use-formatting-locale";
import { getCatalogProduct, getCatalogProducts } from "@/shared/api/catalog";
import { ApiError, apiErrorCode } from "@/shared/api/transport";
import { formatCatalogMoney } from "./format-money";

type PreviewState =
  | { kind: "loading" }
  | { kind: "ready"; products: CatalogProductResponse[] }
  | { kind: "notFound" }
  | { kind: "failed" };

function OfferPreview({ product }: { product: CatalogProductResponse }) {
  const t = useTranslations("CatalogPreview");
  const intlLocale = useIntlLocale();
  const offer = product.offer;

  if (!offer || product.availability === "UNAVAILABLE_AMBIGUOUS_OFFERS") {
    return (
      <div className="approved-offer">
        {product.evidence_mode === "SIMULATED" && <p className="badge badge-demo">{t("simulated")}</p>}
        <p className="card-copy">{t("ambiguous")}</p>
      </div>
    );
  }

  return (
    <div className="approved-offer">
      <p className="badge badge-demo">
        {t(product.availability === "SIMULATED_PREVIEW" ? "simulated" : "unverified")}
      </p>
      <p className="card-copy">{t("previewNote")}</p>
      <dl className="approved-offer-terms">
        <div>
          <dt>{t("recurring")}</dt>
          <dd>{formatCatalogMoney(offer.money.recurring_amount, offer.money.currency, intlLocale)}</dd>
        </div>
        <div>
          <dt>{t("connection")}</dt>
          <dd>{formatCatalogMoney(offer.money.connection_amount, offer.money.currency, intlLocale)}</dd>
        </div>
        <div>
          <dt>{t("period")}</dt>
          <dd>
            <span>{t(`periodUnits.${offer.period.unit}`, { count: offer.period.length })}</span>
            <br />
            <span>{t(`periodAnchors.${offer.period.anchor}`)}</span>
          </dd>
        </div>
        <div>
          <dt>{t("allowance")}</dt>
          <dd>{t("allowanceValue", { quantity: String(offer.allowance.quantity), unit: offer.allowance.unit })}</dd>
        </div>
        <div><dt>{t("metric")}</dt><dd>{offer.allowance.metric_key}</dd></div>
        <div>
          <dt>{t("terms")}</dt>
          <dd>{t(offer.terms.prepaid ? "prepaid" : "paymentUnspecified")}</dd>
        </div>
        <div><dt>{t("tax")}</dt><dd>{t(`taxValues.${offer.terms.tax_treatment}`)}</dd></div>
      </dl>
    </div>
  );
}

export function CatalogPreviewClient({
  productId,
  headingLevel = 2,
  accountStatuses
}: {
  productId?: string;
  headingLevel?: 2 | 3;
  accountStatuses?: {
    [slot in "access" | "usage"]: { label: string; description: string };
  };
}) {
  const t = useTranslations("CatalogPreview");
  const [state, setState] = useState<PreviewState>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);
  // Associate state with its requested ID so navigation never shows old terms.
  const [loadedId, setLoadedId] = useState(productId);

  useEffect(() => {
    let current = true;
    const request = productId === undefined
      ? getCatalogProducts().then((response) => response.products)
      : getCatalogProduct(productId).then((product) => [product]);
    request.then(
      (products) => {
        if (current) {
          setLoadedId(productId);
          setState({ kind: "ready", products });
        }
      },
      (error: unknown) => {
        if (current) {
          setLoadedId(productId);
          setState({ kind: productId !== undefined && error instanceof ApiError &&
            error.status === 404 && apiErrorCode(error) === "catalog_product_not_found"
            ? "notFound" : "failed" });
        }
      }
    );
    return () => { current = false; };
  }, [productId, attempt]);

  const ProductHeading = headingLevel === 2 ? "h2" : "h3";
  const visible: PreviewState = loadedId === productId ? state : { kind: "loading" };
  switch (visible.kind) {
    case "loading":
      return <p role="status">{t("loading")}</p>;
    case "notFound":
      return <p role="status">{t("notFound")}</p>;
    case "failed":
      return (
        <div role="status">
          <p>{t("failed")}</p>
          <button className="btn-secondary" type="button" onClick={() => {
            setState({ kind: "loading" });
            setAttempt((value) => value + 1);
          }}>{t("retry")}</button>
        </div>
      );
    case "ready":
      if (!visible.products.length) return <p role="status">{t("empty")}</p>;
      return (
        <div className={productId === undefined ? "tools-grid" : "approved-offer-detail"}>
          {visible.products.map((product) => (
            <article className="tool-card" key={product.product_id}>
              <ProductHeading>{t("productTitle")}</ProductHeading>
              <p className="catalog-product-id">{product.product_id}</p>
              <OfferPreview product={product} />
              {accountStatuses && (
                <dl className="account-product-statuses">
                  {(["access", "usage"] as const).map((slot) => (
                    <div className="account-product-status" key={slot}>
                      <dt>{accountStatuses[slot].label}</dt>
                      <dd>{accountStatuses[slot].description}</dd>
                    </div>
                  ))}
                </dl>
              )}
              {productId === undefined && (
                <div className="tool-card-bottom">
                  <Link className="tool-detail-action" href={`/products/${encodeURIComponent(product.product_id)}`}>
                    {t("details")}
                  </Link>
                </div>
              )}
            </article>
          ))}
        </div>
      );
  }
}
