"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import type { PurchaseIntentResponse, PurchaseReviewResponse, SessionUserResponse } from "@/generated/api-contracts/types.gen";
import { Link } from "@/i18n/navigation";
import { getSession, sessionStorageKey } from "@/shared/api/auth";
import { advancePurchase, confirmPurchase, currentPurchase, purchaseStatus, reviewPurchase } from "@/shared/api/purchases";
import { ApiError, apiErrorCode } from "@/shared/api/transport";
import { subscribeToSessionChanges, useSessionOperation } from "@/shared/session/use-session-operation";
import {
  billingErrorKey, newRequestId, purchaseReadRefusal, safeRequestId,
  type BillingErrorKey, type PurchaseReadRefusal
} from "./errors";
import { requestPaymentOpening } from "./payment-opening";
import { PurchaseTerms } from "./PurchaseTerms";
import { purchaseNeedsStatus, usePurchaseStatusPoll } from "./use-purchase-status-poll";

type PurchaseState =
  | { kind: "loading" | "unavailable" | "none" }
  | { kind: "review"; review: PurchaseReviewResponse; key: string; selected: string[]; submission: ReviewSubmission }
  | { kind: "purchase"; purchase: PurchaseIntentResponse };
const ReviewSubmission = { Draft: "draft", Submitted: "submitted", Uncertain: "uncertain" } as const;
type ReviewSubmission = typeof ReviewSubmission[keyof typeof ReviewSubmission];
const PurchaseWork = { Idle: "idle", Working: "working", Advancing: "advancing" } as const;
type PurchaseWork = typeof PurchaseWork[keyof typeof PurchaseWork];
type Failure = { message: `errors.${BillingErrorKey}` | PurchaseReadRefusal["message"]; requestId: string; readRefused?: true };
type ProductBillingProps = { productId: string; offerAvailable: boolean; user?: SessionUserResponse; headingLevel?: 2 | 4 };

function commandOutcomeUncertain(error: unknown): boolean {
  if (!(error instanceof ApiError)) return true;
  const code = apiErrorCode(error);
  // A gateway or generic server failure can arrive after the transaction committed.
  return error.status >= 500 && (!code || code === "internal_server_error");
}

function advanceOutcomeUnknown(purchase: PurchaseIntentResponse | null): boolean {
  return !purchase || (purchase.scope_held && (purchase.state === "created" || purchase.state === "awaiting_external_result"));
}

export function ProductBilling({ productId, offerAvailable, user, headingLevel = 2 }: ProductBillingProps) {
  return user
    ? <PurchasePanel key={`${user.user_id}:${productId}`} productId={productId} offerAvailable={offerAvailable} user={user} headingLevel={headingLevel} />
    : <ProductSession key={productId} productId={productId} offerAvailable={offerAvailable} headingLevel={headingLevel} />;
}

function ProductSession({ productId, offerAvailable, headingLevel }: { productId: string; offerAvailable: boolean; headingLevel: 2 | 4 }) {
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
  if (session.kind === "user") return <PurchasePanel key={session.user.user_id} productId={productId} offerAvailable={offerAvailable} user={session.user} headingLevel={headingLevel} />;
  return <section className="purchase-panel" aria-label={t("title")}>
    {session.kind === "loading" ? <p role="status">{t("loading")}</p> : <>
      <p role={session.kind === "failed" ? "alert" : undefined}>{t(session.kind === "guest" ? "guest" : "sessionFailed")}</p>
      {session.kind === "failed" && <button className="btn-secondary" type="button" onClick={() => setAttempt((value) => value + 1)}>{t("retry")}</button>}
      <Link className="btn-secondary" href="/account">{t("signIn")}</Link>
    </>}
  </section>;
}

function PurchasePanel({ productId, offerAvailable, user, headingLevel }: { productId: string; offerAvailable: boolean; user: SessionUserResponse; headingLevel: 2 | 4 }) {
  const t = useTranslations("Purchase");
  const b = useTranslations("Billing");
  const [state, setState] = useState<PurchaseState>({ kind: "loading" });
  const [failure, setFailure] = useState<Failure | null>(null);
  const [work, setWork] = useState<PurchaseWork>(PurchaseWork.Idle);
  const busy = useRef(false);
  const workFinishedAt = useRef(0);
  const refreshButton = useRef<HTMLButtonElement>(null);
  const resumeButton = useRef<HTMLButtonElement>(null);
  const focusPayment = useRef(false);
  const { begin, cancel } = useSessionOperation();
  const Heading = headingLevel === 2 ? "h2" : "h4";
  const ReviewHeading = headingLevel === 2 ? "h3" : "h5";
  const purchase = state.kind === "purchase" ? state.purchase : null;
  const uncertainConfirmation = state.kind === "review" && state.submission === ReviewSubmission.Uncertain;
  const working = work !== PurchaseWork.Idle;
  const advancing = work === PurchaseWork.Advancing;
  const canPoll = user.email_verified && work !== PurchaseWork.Working && !failure?.readRefused;
  const finishWork = useCallback(() => {
    workFinishedAt.current = performance.now();
    busy.current = false;
    setWork(PurchaseWork.Idle);
  }, []);
  const attachPayment = useCallback((link: HTMLAnchorElement | null) => {
    if (!link || !focusPayment.current) return;
    focusPayment.current = false;
    if (document.activeElement === document.body) link.focus();
  }, []);

  const poll = usePurchaseStatusPoll(
    canPoll && purchase?.scope_held && (advancing || purchaseNeedsStatus(purchase)) ? purchase : undefined,
    canPoll && !advancing && uncertainConfirmation ? productId : undefined,
    (saved, readStartedAt) => {
      if (readStartedAt < workFinishedAt.current) return;
      const linked = saved.scope_held && saved.state === "linked";
      if (busy.current) {
        if (!advancing || !linked) return;
        // The saved binding can be used before the POST replies. Retire its UI update.
        cancel();
        finishWork();
      }
      const focused = document.activeElement;
      focusPayment.current = linked && (focused === refreshButton.current || focused === resumeButton.current);
      setState({ kind: "purchase", purchase: saved });
      if (uncertainConfirmation || !saved.scope_held || !purchaseNeedsStatus(saved)) {
        setFailure(null);
      } else if (!advanceOutcomeUnknown(saved)) {
        setFailure((previous) => previous?.message === "errors.financialPending" ? null : previous);
      }
    },
    (refusal) => {
      if (busy.current) {
        if (!advancing) return;
        cancel();
        finishWork();
      }
      setFailure(refusal);
    },
    advancing ? 5_000 : undefined
  );

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
        setFailure(purchaseReadRefusal(error, requestId) ?? { message: `errors.${billingErrorKey(error)}`, requestId: safeRequestId(error) || requestId });
      }
    });
    const unsubscribe = subscribeToSessionChanges(() => {
      cancel();
      finishWork();
      setState({ kind: "unavailable" });
      setFailure({ message: "errors.session", requestId: "" });
    });
    return () => { cancel(); unsubscribe(); };
  }, [begin, cancel, finishWork, productId, user.email_verified]);

  async function run(work: (token: string, requestId: string, current: () => boolean) => Promise<void>) {
    if (busy.current || !user.email_verified) return;
    busy.current = true;
    poll.clearPause();
    setWork(PurchaseWork.Working);
    setFailure(null);
    const operation = begin();
    const requestId = newRequestId();
    try {
      if (!operation.token) throw new ApiError(401, { code: "billing_session_required" });
      await work(operation.token, requestId, operation.isCurrent);
    } catch (error) {
      if (operation.isCurrent()) setFailure({ message: `errors.${billingErrorKey(error)}`, requestId: safeRequestId(error) || requestId, readRefused: failure?.readRefused });
    } finally {
      if (operation.isLatest()) {
        finishWork();
        if (!operation.isCurrent()) {
          setState({ kind: "unavailable" });
          setFailure({ message: "errors.session", requestId });
        }
      }
    }
  }

  function refresh() {
    return run(async (token, id, current) => {
      try {
        const purchase = state.kind === "purchase"
          ? await purchaseStatus(token, state.purchase.purchase_intent_id, id)
          : (await currentPurchase(token, productId, id)).purchase;
        // A lost confirmation may still be completing. Keep its frozen request/key
        // when no hold is visible yet; a local empty GET is not a release proof.
        if (current() && (purchase || state.kind !== "review")) setState(purchase ? { kind: "purchase", purchase } : { kind: "none" });
      } catch (error) {
        const refusal = purchaseReadRefusal(error, id);
        if (!refusal) throw error;
        if (current()) setFailure(refusal);
      }
    });
  }

  function review() {
    return run(async (token, id, current) => {
      const result = await currentPurchase(token, productId, id);
      if (!current()) return;
      if (result.purchase) { setState({ kind: "purchase", purchase: result.purchase }); return; }
      const terms = await reviewPurchase(token, productId, id);
      if (current()) setState({ kind: "review", review: terms, key: newRequestId(), selected: [], submission: ReviewSubmission.Draft });
    });
  }

  async function inspectCommandOutcome(token: string, id: string, current: () => boolean, commandError: unknown, purchaseId?: string) {
    let saved: PurchaseIntentResponse | null = null;
    try {
      saved = purchaseId
        ? await purchaseStatus(token, purchaseId, id)
        : (await currentPurchase(token, productId, id)).purchase;
    } catch (error) {
      const refusal = purchaseReadRefusal(error, id);
      if (refusal) {
        if (current()) setFailure(refusal);
        return;
      }
    }
    if (!current()) return;
    if (saved) setState({ kind: "purchase", purchase: saved });
    // A saved intent proves confirmation. Advance also needs evidence of preparation.
    const pending = purchaseId ? advanceOutcomeUnknown(saved) : !saved;
    setFailure(pending ? { message: "errors.financialPending", requestId: safeRequestId(commandError) || id } : null);
  }

  async function prepare(token: string, purchase: PurchaseIntentResponse, id: string, current: () => boolean) {
    setWork(PurchaseWork.Advancing);
    let result: PurchaseIntentResponse;
    try {
      result = await advancePurchase(token, purchase.purchase_intent_id, id);
    } catch (error) {
      if (!commandOutcomeUncertain(error) && apiErrorCode(error) !== "preflight_deadline_exceeded") throw error;
      if (current()) await inspectCommandOutcome(token, id, current, error, purchase.purchase_intent_id);
      return;
    }
    if (!current()) return;
    setState({ kind: "purchase", purchase: result });
  }

  function confirm() {
    if (state.kind !== "review" || !state.review.documents.length || state.selected.length !== state.review.documents.length) return;
    const frozen = state;
    return run(async (token, id, current) => {
      if (frozen.submission === ReviewSubmission.Draft) setState({ ...frozen, submission: ReviewSubmission.Submitted });
      let result: PurchaseIntentResponse;
      try {
        result = await confirmPurchase(token, {
          product_id: productId, revision_id: frozen.review.revision_id,
          expected_fingerprint: frozen.review.expected_fingerprint,
          expected_technical_terms_digest: frozen.review.expected_technical_terms_digest,
          documents: frozen.review.documents.map(({ document_version_id, acceptance_text_hash }) => ({ document_version_id, acceptance_text_hash }))
        }, frozen.key, id);
      } catch (error) {
        if (current() && apiErrorCode(error) === "terms_changed") {
          // Definitive refusal before pin: a new explicit review/consent is needed.
          setState({ kind: "none" });
        } else if (current() && ["purchase_scope_occupied", "purchase_idempotency_conflict"].includes(apiErrorCode(error) ?? "")) {
          try {
            const existing = await currentPurchase(token, productId, id);
            if (current() && existing.purchase) {
              setState({ kind: "purchase", purchase: existing.purchase });
              return;
            }
          } catch { /* Preserve the original conflict and request ID if inspection fails. */ }
        } else if (current() && commandOutcomeUncertain(error)) {
          // Freeze the original key and consent until the accepted intent is found.
          setState({ ...frozen, submission: ReviewSubmission.Uncertain });
          await inspectCommandOutcome(token, id, current, error);
          return;
        }
        throw error;
      }
      if (!current()) return;
      setState({ kind: "purchase", purchase: result });
      if (result.state === "created" || result.state === "preparing" || result.state === "awaiting_external_result") await prepare(token, result, id, current);
    });
  }

  const linked = purchase?.state === "linked";
  const resumable = purchase && purchase.scope_held && !linked;
  const needsRecovery = purchase?.state === "awaiting_external_result" || purchase?.state === "manual_review";
  const released = purchase && !purchase.scope_held && (purchase.state === "resolved_no_external_effect" || purchase.state === "failed_before_external_effect");
  return <section className={linked ? "purchase-panel purchase-complete" : "purchase-panel"} aria-label={t("title")}>
    {!linked && <Heading>{t("title")}</Heading>}
    <div role="status">
      {linked ? <Heading>{t("states.linked")}</Heading> : purchase && <p>{t(`states.${purchase.state}`)}</p>}
    </div>
    {linked ? <>
      <p className="card-copy">{t("managedInAccount")}</p>
      <p className="card-copy">{t("accessInAccount")}</p>
      <Link ref={attachPayment} className="btn-primary" href={`/account?purchase=${encodeURIComponent(purchase.purchase_intent_id)}#billing`}
        onNavigate={() => requestPaymentOpening(purchase.purchase_intent_id, user.user_id)}>{b("pay")}</Link>
      <details><summary>{t("acceptedTerms")}</summary><PurchaseTerms review={purchase.accepted} /></details>
    </> : !user.email_verified ? <>
      <p>{t("verification")}</p>
      <Link className="btn-secondary" href="/account">{t("verifyAction")}</Link>
    </> : <>
      <div className="purchase-actions">
        {(state.kind === "none" || released) && <button className="btn-primary" type="button" disabled={working || !offerAvailable} onClick={() => void review()}>{t("buy")}</button>}
        {(state.kind === "unavailable" || state.kind === "review" || purchase) && <button ref={refreshButton} className="btn-secondary" type="button" disabled={working} onClick={() => void refresh()}>{t("refresh")}</button>}
      </div>
      {state.kind === "loading" && <p role="status">{t("loading")}</p>}
      {working && <p role="status">{t("working")}</p>}
      {poll.paused && <p role="status">{t("statusPollingPaused")}</p>}
      {state.kind === "unavailable" && <p>{t("unknown")}</p>}
      {state.kind === "review" && <div className="purchase-review">
        <ReviewHeading>{t("reviewTitle")}</ReviewHeading>
        <PurchaseTerms review={state.review} />
        <p>{t("draftLegal")}</p>
        <fieldset className="purchase-consents" disabled={working || state.submission !== ReviewSubmission.Draft}>
          <legend>{t("consents")}</legend>
          {state.review.documents.map((doc) => <div key={doc.document_version_id}>
            <a href={doc.url_path} lang="ru" target="_blank" rel="noreferrer">{doc.title} · {doc.version}</a>
            <label className="checkbox-row"><input type="checkbox" checked={state.selected.includes(doc.document_version_id)} onChange={(event) => {
              const checked = event.target.checked;
              setState({ ...state, selected: checked ? [...state.selected, doc.document_version_id] : state.selected.filter((id) => id !== doc.document_version_id) });
            }} /><span lang="ru">{doc.acceptance_text}</span></label>
          </div>)}
        </fieldset>
        {state.submission !== ReviewSubmission.Draft && <p>{t("confirmationUncertain")}</p>}
        <button className="btn-primary" type="button" disabled={working || failure?.readRefused || !state.review.documents.length || state.selected.length !== state.review.documents.length} onClick={() => void confirm()}>{t(state.submission === ReviewSubmission.Draft ? "confirm" : "retryConfirm")}</button>
      </div>}
      {purchase && <div className="purchase-status">
        {purchase.reason && <p>{t(purchase.reason === "terms_changed" ? "termsChanged" : purchase.reason === "purchase_pending" ? "pending" : "reviewRequired")}</p>}
        <p className="catalog-product-id">{t("reference", { id: purchase.purchase_intent_id })}</p>
        <details><summary>{t("acceptedTerms")}</summary><PurchaseTerms review={purchase.accepted} /></details>
        {resumable && !failure?.readRefused && <button ref={resumeButton} className="btn-primary" type="button" disabled={working} onClick={() => void run((token, id, current) => prepare(token, purchase, id, current))}>{t(needsRecovery ? "recover" : "continue")}</button>}
        <p>{t("awaitingVerification")}</p>
      </div>}
      {failure && <div className="notice error" role="alert">{b(failure.message)}{failure.requestId && <p>{b("requestId", { id: failure.requestId })}</p>}</div>}
      <p className="card-copy">{t("accessInAccount")}</p>
    </>}
  </section>;
}
