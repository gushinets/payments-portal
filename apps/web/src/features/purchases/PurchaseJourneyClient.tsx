"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore
} from "react";
import { useTranslations } from "next-intl";

import type {
  ProductPurchaseStatusResponse,
  PurchaseRequest,
  PurchaseResponse,
  PurchaseReviewResponse
} from "@/generated/api-contracts/types.gen";
import { Link } from "@/i18n/navigation";
import { getSession, sessionStorageKey } from "@/shared/api/auth";
import {
  bootstrapWidget,
  continuePurchase,
  createPurchase,
  getProductPurchaseStatus,
  getPurchase,
  getPurchaseReview
} from "@/shared/api/purchases";
import { ApiError, apiErrorCode } from "@/shared/api/transport";
import {
  subscribeToSessionChanges,
  useSessionOperation
} from "@/shared/session/use-session-operation";

import { PurchaseReview } from "./PurchaseReview";

type ReadyView = {
  kind: "ready";
  status: ProductPurchaseStatusResponse["state"] | "uncertain";
  review: PurchaseReviewResponse | null;
  purchase: PurchaseResponse | null;
  userId: string;
};
type View =
  | { kind: "loading" | "signedOut" | "ineligible" | "failed" }
  | ReadyView;
type ErrorKey =
  | "failed"
  | "conflict"
  | "notReady"
  | "reviewNeeded"
  | "ineligible";

function errorKey(error: unknown): ErrorKey {
  switch (apiErrorCode(error)) {
    case "identity_conflict":
    case "commercial_terms_conflict":
    case "idempotency_conflict":
      return "conflict";
    case "manual_review_required":
      return "reviewNeeded";
    case "billing_not_ready":
    case "purchase_not_enabled":
      return "notReady";
    case "purchase_ineligible":
      return "ineligible";
    default:
      return "failed";
  }
}

function hasPortalSession(): boolean {
  return Boolean(window.localStorage.getItem(sessionStorageKey));
}

function serverHasPortalSession(): boolean {
  return false;
}

async function readPurchaseView(
  productId: string,
  token: string,
  isCurrent: () => boolean
): Promise<View | null> {
  const session = await getSession(token);
  if (!isCurrent()) return null;
  if (!session.user.email_verified) return { kind: "ineligible" };
  const status = await getProductPurchaseStatus(productId, token);
  if (!isCurrent()) return null;
  const purchase = status.purchase_intent_id
    ? await getPurchase(status.purchase_intent_id, token)
    : null;
  if (!isCurrent()) return null;
  const review =
    purchase?.accepted_terms ??
    (status.state === "not_ready"
      ? await getPurchaseReview(productId, token)
      : null);
  if (!isCurrent()) return null;
  return {
    kind: "ready",
    status: status.state,
    purchase,
    review,
    userId: session.user.user_id
  };
}

export function PurchaseJourneyClient({ productId }: { productId: string }) {
  const t = useTranslations("Purchase");
  const { begin, cancel } = useSessionOperation();
  const hasSession = useSyncExternalStore(
    subscribeToSessionChanges,
    hasPortalSession,
    serverHasPortalSession
  );
  const [storedView, setView] = useState<View>({ kind: "loading" });
  const view: View = hasSession ? storedView : { kind: "signedOut" };
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const [error, setError] = useState<ErrorKey | null>(null);
  const [commercial, setCommercial] = useState(false);
  const [recurring, setRecurring] = useState(false);
  const [documents, setDocuments] = useState<Set<string>>(new Set());
  const [widgetOpen, setWidgetOpen] = useState(false);
  const widgetNode = useRef<HTMLDivElement>(null);
  const widgetDispose = useRef<(() => void) | null>(null);
  const openButton = useRef<HTMLButtonElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);

  const clearWidget = useCallback(() => {
    widgetDispose.current?.();
    widgetDispose.current = null;
    widgetNode.current?.replaceChildren();
    setWidgetOpen(false);
  }, []);

  const load = useCallback(() => {
    const operation = begin();
    if (!operation.token) return;
    void readPurchaseView(productId, operation.token, operation.isCurrent).then(
      (result) => {
        if (operation.isCurrent() && result) setView(result);
      },
      (failure: unknown) => {
        if (!operation.isCurrent()) return;
        setError(errorKey(failure));
        setView({
          kind:
            failure instanceof ApiError && failure.status === 401
              ? "signedOut"
              : "failed"
        });
      }
    );
  }, [begin, productId]);

  const reload = useCallback(() => {
    cancel();
    clearWidget();
    setView({ kind: "loading" });
    busyRef.current = false;
    setBusy(false);
    setError(null);
    setCommercial(false);
    setRecurring(false);
    setDocuments(new Set());
    void load();
  }, [cancel, clearWidget, load]);

  useEffect(() => {
    const unsubscribe = subscribeToSessionChanges(reload);
    void load();
    return () => {
      unsubscribe();
      cancel();
      widgetDispose.current?.();
      widgetDispose.current = null;
    };
  }, [cancel, load, reload]);

  useEffect(() => {
    if (widgetOpen) closeButton.current?.focus();
  }, [widgetOpen]);

  async function act(action: "purchase" | "continue" | "refresh" | "widget") {
    if (view.kind !== "ready" || busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setError(null);
    const operation = begin();
    if (!operation.token) {
      busyRef.current = false;
      setBusy(false);
      setView({ kind: "signedOut" });
      return;
    }
    try {
      if (action === "widget") {
        // Load the allowlisted SDK host only after an intentional click.
        const sdk = await import("./official-widget-sdk");
        if (!operation.isCurrent()) return;
        const bootstrap = await bootstrapWidget(
          {
            product_id: productId,
            purchase_intent_id: view.purchase?.purchase_intent_id
          },
          operation.token
        );
        if (!operation.isCurrent() || !widgetNode.current) {
          bootstrap.credential = "";
          return;
        }
        widgetDispose.current?.();
        try {
          if (bootstrap.mode === "SIMULATED" && process.env.NODE_ENV !== "production") {
            // Regression harness only; runtime stand bootstrap always uses LOCAL_043.
            const recorded = await import("./simulated-widget-sdk");
            if (!operation.isCurrent() || !widgetNode.current) return;
            widgetDispose.current = recorded.mountSimulatedWidget(widgetNode.current, bootstrap, t("stub"));
          } else {
            widgetDispose.current = sdk.mountOfficialWidget(
              widgetNode.current, bootstrap, t("title"), operation.isCurrent,
              () => { clearWidget(); setError("notReady"); }
            );
          }
        } finally {
          bootstrap.credential = "";
        }
        if (operation.isCurrent()) setWidgetOpen(true);
        return;
      }
      let purchase: PurchaseResponse | null = null;
      if (action === "purchase" && view.review) {
        const review = view.review;
        if (
          review.availability !== "SIMULATED_PREVIEW" ||
          !commercial ||
          (review.recurring_required && !recurring) ||
          documents.size !== review.documents.length
        )
          return;
        const payload: PurchaseRequest = {
          product_id: productId,
          revision_id: review.offer.revision_id,
          expected_fingerprint: review.fingerprint,
          commercial_confirmation: true,
          recurring_confirmation: review.recurring_required,
          documents: review.documents.map((doc) => ({
            document_version_id: doc.document_version_id,
            acceptance_text_hash: doc.acceptance_text_hash
          }))
        };
        // This nonsecret key survives a lost reply/reload. Only a UUID is read;
        // no credential, legal body or purchase response is put in storage.
        const slot = `portal_purchase_attempt:${view.userId}:${productId}:${review.fingerprint}`;
        const saved = window.sessionStorage.getItem(slot);
        const key =
          saved && /^[0-9a-f-]{36}$/.test(saved) ? saved : crypto.randomUUID();
        window.sessionStorage.setItem(slot, key);
        purchase = await createPurchase(payload, key, operation.token);
      } else if (action === "continue" && view.purchase) {
        purchase = await continuePurchase(
          view.purchase.purchase_intent_id,
          operation.token
        );
      }
      if (!operation.isCurrent()) return;
      const status = await getProductPurchaseStatus(productId, operation.token);
      if (!purchase && status.purchase_intent_id)
        purchase = await getPurchase(
          status.purchase_intent_id,
          operation.token
        );
      if (operation.isCurrent())
        setView({
          ...view,
          status: status.state,
          purchase,
          review: purchase?.accepted_terms ?? view.review
        });
    } catch (failure) {
      if (!operation.isCurrent()) return;
      setError(errorKey(failure));
      if (action === "purchase" || action === "continue") {
        // A 5s client timeout cannot revoke the server's committed operation.
        // Recover by owned status; never automatically repeat CREATE/continue.
        setView({ ...view, status: "uncertain" });
        try {
          const status = await getProductPurchaseStatus(
            productId,
            operation.token
          );
          const purchase = status.purchase_intent_id
            ? await getPurchase(status.purchase_intent_id, operation.token)
            : null;
          if (operation.isCurrent())
            setView({
              ...view,
              status: purchase ? status.state : "uncertain",
              purchase,
              review: purchase?.accepted_terms ?? view.review
            });
        } catch {
          /* Keep the explicit status-recovery action available. */
        }
      }
    } finally {
      if (operation.isLatest()) {
        busyRef.current = false;
        setBusy(false);
      }
    }
  }

  function closeWidget() {
    cancel();
    clearWidget();
    busyRef.current = false;
    setBusy(false);
    openButton.current?.focus();
  }

  const review = view.kind === "ready" ? view.review : null;
  return (
    <section
      className="purchase-journey"
      aria-label={t("title")}
      aria-busy={busy}
    >
      <h2>{t("title")}</h2>
      <p className="card-copy">{t("noAccess")}</p>
      {error && (
        <p className="notice error" role="alert">
          {t(error)}
        </p>
      )}
      {view.kind === "loading" && <p role="status">{t("loading")}</p>}
      {view.kind === "signedOut" && (
        <Link className="btn-secondary" href="/account">
          {t("signIn")}
        </Link>
      )}
      {view.kind === "ineligible" && <p role="status">{t("ineligible")}</p>}
      {view.kind === "failed" && (
        <button type="button" className="btn-secondary" onClick={reload}>
          {t("refresh")}
        </button>
      )}
      {view.kind === "ready" && (
        <>
          <p role="status">{t(`states.${view.status}`)}</p>
          {view.purchase && (
            <p className="purchase-reference">
              {t("reference", { id: view.purchase.purchase_intent_id })}
            </p>
          )}
          {review && (
            <PurchaseReview
              review={review}
              showConsent={
                !view.purchase &&
                view.status === "not_ready" &&
                review.availability === "SIMULATED_PREVIEW"
              }
              busy={busy}
              commercial={commercial}
              recurring={recurring}
              documents={documents}
              onCommercialChange={setCommercial}
              onRecurringChange={setRecurring}
              onDocumentChange={(documentId, checked) =>
                setDocuments((previous) => {
                  const next = new Set(previous);
                  if (checked) next.add(documentId);
                  else next.delete(documentId);
                  return next;
                })
              }
              onSubmit={() => void act("purchase")}
            />
          )}
          <div className="purchase-actions">
            <button
              type="button"
              className="btn-secondary"
              disabled={busy}
              onClick={() => void act("refresh")}
            >
              {t("refresh")}
            </button>
            {view.purchase?.continue_available && (
              <button
                type="button"
                className="btn-primary"
                disabled={busy}
                onClick={() => void act("continue")}
              >
                {t("continue")}
              </button>
            )}
            {view.status === "manage" && (
              <button
                type="button"
                ref={openButton}
                className="btn-primary"
                disabled={busy || widgetOpen}
                onClick={() => void act("widget")}
              >
                {t("manage")}
              </button>
            )}
          </div>
        </>
      )}
      <div
        className="purchase-widget"
        hidden={!widgetOpen}
        onKeyDown={(event) => {
          if (event.key === "Escape") closeWidget();
        }}
      >
        <div ref={widgetNode} />
        <button
          type="button"
          ref={closeButton}
          className="btn-secondary"
          onClick={closeWidget}
        >
          {t("close")}
        </button>
      </div>
    </section>
  );
}
