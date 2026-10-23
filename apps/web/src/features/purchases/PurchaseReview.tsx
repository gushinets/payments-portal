"use client";

import { useTranslations } from "next-intl";

import type { PurchaseReviewResponse } from "@/generated/api-contracts/types.gen";

type PurchaseReviewProps = {
  review: PurchaseReviewResponse;
  showConsent: boolean;
  busy: boolean;
  commercial: boolean;
  recurring: boolean;
  documents: ReadonlySet<string>;
  onCommercialChange: (checked: boolean) => void;
  onRecurringChange: (checked: boolean) => void;
  onDocumentChange: (documentId: string, checked: boolean) => void;
  onSubmit: () => void;
};

export function PurchaseReview({
  review,
  showConsent,
  busy,
  commercial,
  recurring,
  documents,
  onCommercialChange,
  onRecurringChange,
  onDocumentChange,
  onSubmit
}: PurchaseReviewProps) {
  const t = useTranslations("Purchase");
  const catalog = useTranslations("CatalogPreview");

  return (
    <>
      <p className="badge badge-demo">
        {catalog(
          review.availability === "SIMULATED_PREVIEW"
            ? "simulated"
            : "unverified"
        )}
      </p>
      <dl className="approved-offer-terms">
        <div>
          <dt>{t("seller")}</dt>
          <dd>{review.seller_name}</dd>
        </div>
        <div>
          <dt>{t("service")}</dt>
          <dd>{review.product_id}</dd>
        </div>
        <div>
          <dt>{t("initial")}</dt>
          <dd>
            {review.initial_amount} {review.offer.money.currency}
          </dd>
        </div>
        <div>
          <dt>{catalog("recurring")}</dt>
          <dd>
            {review.offer.money.recurring_amount} {review.offer.money.currency}
          </dd>
        </div>
        <div>
          <dt>{catalog("connection")}</dt>
          <dd>
            {review.offer.money.connection_amount} {review.offer.money.currency}
          </dd>
        </div>
        <div>
          <dt>{catalog("period")}</dt>
          <dd>
            {catalog(`periodUnits.${review.offer.period.unit}`, {
              count: review.offer.period.length
            })}
            {" · "}
            <span>{catalog(`periodAnchors.${review.offer.period.anchor}`)}</span>
          </dd>
        </div>
        <div>
          <dt>{catalog("allowance")}</dt>
          <dd>
            {catalog("allowanceValue", {
              quantity: review.offer.allowance.quantity,
              unit: review.offer.allowance.unit
            })}
          </dd>
        </div>
        <div>
          <dt>{t("renewal")}</dt>
          <dd>{review.renewal_terms}</dd>
        </div>
        <div>
          <dt>{t("cancellation")}</dt>
          <dd>{review.cancellation_terms}</dd>
        </div>
      </dl>
      {showConsent && (
        <form
          className="form-grid"
          onSubmit={(event) => {
            event.preventDefault();
            onSubmit();
          }}
        >
          <p className="notice">{t("draftLegal")}</p>
          {review.documents.map((doc) => (
            <label
              className="purchase-consent"
              key={doc.document_version_id}
              lang="ru"
            >
              <input
                type="checkbox"
                required
                checked={documents.has(doc.document_version_id)}
                disabled={busy}
                onChange={(event) =>
                  onDocumentChange(
                    doc.document_version_id,
                    event.target.checked
                  )
                }
              />
              <span>
                {doc.acceptance_text}{" "}
                <a href={doc.url_path} target="_blank" rel="noreferrer">
                  {doc.title} ({doc.version})
                </a>
              </span>
            </label>
          ))}
          <label className="purchase-consent">
            <input
              type="checkbox"
              required
              checked={commercial}
              disabled={busy}
              onChange={(event) => onCommercialChange(event.target.checked)}
            />
            <span>{t("commercialConsent")}</span>
          </label>
          {review.recurring_required && (
            <label className="purchase-consent">
              <input
                type="checkbox"
                required
                checked={recurring}
                disabled={busy}
                onChange={(event) => onRecurringChange(event.target.checked)}
              />
              <span>{t("recurringConsent")}</span>
            </label>
          )}
          <button
            type="submit"
            className="btn-primary"
            disabled={
              busy ||
              !commercial ||
              (review.recurring_required && !recurring) ||
              documents.size !== review.documents.length
            }
          >
            {t("purchase")}
          </button>
        </form>
      )}
    </>
  );
}
