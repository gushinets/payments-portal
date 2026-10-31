"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import type { PurchaseIntentResponse, PurchaseReviewResponse, SessionUserResponse } from "@/generated/api-contracts/types.gen";
import { Link } from "@/i18n/navigation";
import { getSession, sessionStorageKey } from "@/shared/api/auth";
import { advancePurchase, confirmPurchase, currentPurchase, purchaseStatus, reviewPurchase } from "@/shared/api/purchases";
import { ApiError, apiErrorCode } from "@/shared/api/transport";
import { subscribeToSessionChanges, useSessionOperation } from "@/shared/session/use-session-operation";
import { billingErrorKey, newRequestId, safeRequestId, type BillingErrorKey } from "./errors";
import { PurchaseTerms } from "./PurchaseTerms";

type PurchaseState =
  | { kind: "loading" | "unavailable" | "none" }
  | { kind: "review"; review: PurchaseReviewResponse; key: string; selected: string[]; submitted: boolean }
  | { kind: "purchase"; purchase: PurchaseIntentResponse };
type Failure = { message: BillingErrorKey; requestId: string };
type ProductBillingProps = { productId: string; user?: SessionUserResponse; headingLevel?: 2 | 4 };

export function ProductBilling({ productId, user, headingLevel = 2 }: ProductBillingProps) {
  return user
    ? <PurchasePanel key={`${user.user_id}:${productId}`} productId={productId} user={user} headingLevel={headingLevel} />
    : <ProductSession key={productId} productId={productId} headingLevel={headingLevel} />;
}

function ProductSession({ productId, headingLevel }: { productId: string; headingLevel: 2 | 4 }) {
  const t = useTranslations("Purchase");
  const [session, setSession] = useState<{ kind: "loading" | "guest" | "failed" } | { kind: "user"; user: SessionUserResponse }>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    let version = 0;
    async function load() {
      const request = ++version;
      const token = window.localStorage.getItem(sessionStorageKey);
      const current = () => {
        if (!active || request !== version) return false;
        if (window.localStorage.getItem(sessionStorageKey) !== token) { void load(); return false; }
        return true;
      };
      if (!token) { if (active) setSession({ kind: "guest" }); return; }
      setSession({ kind: "loading" });
      try {
        const result = await getSession(token);
        if (current()) setSession(result.authenticated ? { kind: "user", user: result.user } : { kind: "guest" });
      } catch (error) {
        if (current()) setSession({ kind: error instanceof ApiError && error.status === 401 ? "guest" : "failed" });
      }
    }
    const unsubscribe = subscribeToSessionChanges(() => void load());
    void load();
    return () => { active = false; unsubscribe(); };
  }, [attempt]);
  if (session.kind === "user") return <PurchasePanel key={session.user.user_id} productId={productId} user={session.user} headingLevel={headingLevel} />;
  return <section className="purchase-panel" aria-label={t("title")}>
    {session.kind === "loading" ? <p role="status">{t("loading")}</p> : <>
      <p role={session.kind === "failed" ? "alert" : undefined}>{t(session.kind === "guest" ? "guest" : "sessionFailed")}</p>
      {session.kind === "failed" && <button className="btn-secondary" type="button" onClick={() => setAttempt((value) => value + 1)}>{t("retry")}</button>}
      <Link className="btn-secondary" href="/account">{t("signIn")}</Link>
    </>}
  </section>;
}

function PurchasePanel({ productId, user, headingLevel }: { productId: string; user: SessionUserResponse; headingLevel: 2 | 4 }) {
  const t = useTranslations("Purchase");
  const b = useTranslations("Billing");
  const [state, setState] = useState<PurchaseState>({ kind: "loading" });
  const [failure, setFailure] = useState<Failure | null>(null);
  const [working, setWorking] = useState(false);
  const busy = useRef(false);
  const { begin, cancel } = useSessionOperation();
  const Heading = headingLevel === 2 ? "h2" : "h4";
  const ReviewHeading = headingLevel === 2 ? "h3" : "h5";

  useEffect(() => {
    if (!user.email_verified) return;
    const operation = begin();
    const requestId = newRequestId();
    async function load() {
      if (!operation.token) throw new ApiError(401, { code: "billing_session_required" });
      return currentPurchase(operation.token, productId, requestId);
    }
    load().then((result) => {
      if (operation.isCurrent()) setState(result.purchase ? { kind: "purchase", purchase: result.purchase } : { kind: "none" });
    }, (error: unknown) => {
      if (operation.isCurrent()) {
        setState({ kind: "unavailable" });
        setFailure({ message: billingErrorKey(error), requestId: safeRequestId(error) || requestId });
      }
    });
    const unsubscribe = subscribeToSessionChanges(() => {
      cancel();
      busy.current = false;
      setWorking(false);
      setState({ kind: "unavailable" });
      setFailure({ message: "session", requestId: "" });
    });
    return () => { cancel(); unsubscribe(); };
  }, [begin, cancel, productId, user.email_verified]);

  async function run(work: (token: string, requestId: string, current: () => boolean) => Promise<void>) {
    if (busy.current || !user.email_verified) return;
    busy.current = true;
    setWorking(true);
    setFailure(null);
    const operation = begin();
    const requestId = newRequestId();
    try {
      if (!operation.token) throw new ApiError(401, { code: "billing_session_required" });
      await work(operation.token, requestId, operation.isCurrent);
    } catch (error) {
      if (operation.isCurrent()) setFailure({ message: billingErrorKey(error), requestId: safeRequestId(error) || requestId });
    } finally {
      if (operation.isLatest()) {
        busy.current = false;
        setWorking(false);
        if (!operation.isCurrent()) {
          setState({ kind: "unavailable" });
          setFailure({ message: "session", requestId });
        }
      }
    }
  }

  function refresh() {
    return run(async (token, id, current) => {
      if (state.kind === "purchase") {
        const purchase = await purchaseStatus(token, state.purchase.purchase_intent_id, id);
        if (current()) setState({ kind: "purchase", purchase });
      } else {
        const result = await currentPurchase(token, productId, id);
        // A lost confirmation may still be completing. Keep its frozen request/key
        // when no hold is visible yet; a local empty GET is not a release proof.
        if (current() && (result.purchase || state.kind !== "review")) setState(result.purchase ? { kind: "purchase", purchase: result.purchase } : { kind: "none" });
      }
    });
  }

  function review() {
    return run(async (token, id, current) => {
      const result = await currentPurchase(token, productId, id);
      if (!current()) return;
      if (result.purchase) { setState({ kind: "purchase", purchase: result.purchase }); return; }
      const terms = await reviewPurchase(token, productId, id);
      if (current()) setState({ kind: "review", review: terms, key: newRequestId(), selected: [], submitted: false });
    });
  }

  async function prepare(token: string, purchase: PurchaseIntentResponse, id: string, current: () => boolean) {
    let result: PurchaseIntentResponse;
    try {
      result = await advancePurchase(token, purchase.purchase_intent_id, id);
    } catch (error) {
      if (error instanceof ApiError) throw error;
      // A browser timeout/disconnect does not cancel the server's financial work.
      // Inspect once locally; never replay advance or authorize payment from this GET.
      let saved: PurchaseIntentResponse | null = null;
      try { saved = await purchaseStatus(token, purchase.purchase_intent_id, id); }
      catch { /* Keep the original held intent visible if the status read also fails. */ }
      if (current()) {
        if (saved) setState({ kind: "purchase", purchase: saved });
        setFailure(saved?.state === "linked" ? null : { message: "financialPending", requestId: id });
      }
      return;
    }
    if (!current()) return;
    setState({ kind: "purchase", purchase: result });
  }

  function confirm() {
    if (state.kind !== "review" || !state.review.documents.length || state.selected.length !== state.review.documents.length) return;
    const frozen = state;
    return run(async (token, id, current) => {
      setState({ ...frozen, submitted: true });
      let result: PurchaseIntentResponse;
      try {
        result = await confirmPurchase(token, {
          product_id: productId, revision_id: frozen.review.revision_id,
          expected_fingerprint: frozen.review.expected_fingerprint,
          documents: frozen.review.documents.map(({ document_version_id, acceptance_text_hash }) => ({ document_version_id, acceptance_text_hash }))
        }, frozen.key, id);
      } catch (error) {
        if (current() && apiErrorCode(error) === "terms_changed") {
          // Definitive refusal before pin: a new explicit review/consent is needed.
          setState({ kind: "none" });
        } else if (current() && ["purchase_scope_occupied", "purchase_idempotency_conflict"].includes(apiErrorCode(error) ?? "")) {
          const existing = await currentPurchase(token, productId, id);
          if (current() && existing.purchase) setState({ kind: "purchase", purchase: existing.purchase });
        } else if (current() && !(error instanceof ApiError)) {
          // Recover an accepted intent from a lost response, without a second POST.
          // An empty/failed GET retains the frozen confirmation and its original key.
          try {
            const existing = await currentPurchase(token, productId, id);
            if (current() && existing.purchase) setState({ kind: "purchase", purchase: existing.purchase });
          } catch { /* The exact submitted review remains reserved in this view. */ }
          if (current()) setFailure({ message: "financialPending", requestId: id });
          return;
        }
        throw error;
      }
      if (!current()) return;
      setState({ kind: "purchase", purchase: result });
      if (result.state === "created" || result.state === "preparing" || result.state === "awaiting_external_result") await prepare(token, result, id, current);
    });
  }

  const purchase = state.kind === "purchase" ? state.purchase : null;
  const resumable = purchase && purchase.scope_held && purchase.state !== "linked";
  const released = purchase && !purchase.scope_held && (purchase.state === "resolved_no_external_effect" || purchase.state === "failed_before_external_effect");
  if (purchase?.state === "linked") return <section className="purchase-panel purchase-complete" aria-label={t("title")}>
    <Heading>{t("states.linked")}</Heading>
    <p className="card-copy">{t("managedInAccount")}</p>
    <Link className="btn-primary" href={`/account?purchase=${encodeURIComponent(purchase.purchase_intent_id)}#billing`}>{t("manage")}</Link>
    <details><summary>{t("acceptedTerms")}</summary><PurchaseTerms review={purchase.accepted} /></details>
  </section>;
  return <section className="purchase-panel" aria-label={t("title")}>
    <Heading>{t("title")}</Heading>
    {!user.email_verified ? <>
      <p>{t("verification")}</p>
      <Link className="btn-secondary" href="/account">{t("verifyAction")}</Link>
    </> : <>
      <div className="purchase-actions">
        {(state.kind === "none" || released) && <button className="btn-primary" type="button" disabled={working} onClick={() => void review()}>{t("buy")}</button>}
        {(state.kind === "unavailable" || state.kind === "review" || purchase) && <button className="btn-secondary" type="button" disabled={working} onClick={() => void refresh()}>{t("refresh")}</button>}
      </div>
      {state.kind === "loading" && <p role="status">{t("loading")}</p>}
      {working && <p role="status">{t("working")}</p>}
      {state.kind === "unavailable" && <p>{t("unknown")}</p>}
      {state.kind === "review" && <div className="purchase-review">
        <ReviewHeading>{t("reviewTitle")}</ReviewHeading>
        <PurchaseTerms review={state.review} />
        <p>{t("draftLegal")}</p>
        <fieldset className="purchase-consents" disabled={working || state.submitted}>
          <legend>{t("consents")}</legend>
          {state.review.documents.map((doc) => <div key={doc.document_version_id}>
            <a href={doc.url_path} lang="ru" target="_blank" rel="noreferrer">{doc.title} · {doc.version}</a>
            <label className="checkbox-row"><input type="checkbox" checked={state.selected.includes(doc.document_version_id)} onChange={(event) => {
              const checked = event.target.checked;
              setState({ ...state, selected: checked ? [...state.selected, doc.document_version_id] : state.selected.filter((id) => id !== doc.document_version_id) });
            }} /><span lang="ru">{doc.acceptance_text}</span></label>
          </div>)}
        </fieldset>
        {state.submitted && <p>{t("confirmationUncertain")}</p>}
        <button className="btn-primary" type="button" disabled={working || !state.review.documents.length || state.selected.length !== state.review.documents.length} onClick={() => void confirm()}>{t(state.submitted ? "retryConfirm" : "confirm")}</button>
      </div>}
      {purchase && <div className="purchase-status">
        <p role="status">{t(`states.${purchase.state}`)}</p>
        {purchase.reason && <p>{t(purchase.reason === "terms_changed" ? "termsChanged" : purchase.reason === "purchase_pending" ? "pending" : "reviewRequired")}</p>}
        <p className="catalog-product-id">{t("reference", { id: purchase.purchase_intent_id })}</p>
        <details><summary>{t("acceptedTerms")}</summary><PurchaseTerms review={purchase.accepted} /></details>
        {resumable && <button className="btn-primary" type="button" disabled={working} onClick={() => void run((token, id, current) => prepare(token, purchase, id, current))}>{t(purchase.state === "created" ? "continue" : "recover")}</button>}
        <p>{t("awaitingVerification")}</p>
      </div>}
      {failure && <div className="notice error" role="alert">{b(`errors.${failure.message}`)}{failure.requestId && <p>{b("requestId", { id: failure.requestId })}</p>}</div>}
      <p className="card-copy">{t("accessDeferred")}</p>
    </>}
  </section>;
}
