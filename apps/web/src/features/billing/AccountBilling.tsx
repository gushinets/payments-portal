"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";
import { purchaseStatus } from "@/shared/api/purchases";
import { subscribeToSessionChanges, useSessionOperation } from "@/shared/session/use-session-operation";
import { newRequestId, purchaseReadRefusal, reportBillingSessionRefusal, safeRequestId, type PurchaseReadRefusal } from "./errors";
import { claimPaymentOpening } from "./payment-opening";
import { useAccountPurchases } from "./use-account-purchases";
import { WidgetStatus, useBillingWidget } from "./use-billing-widget";
import { purchaseNeedsStatus, usePurchaseStatusPoll } from "./use-purchase-status-poll";
import { WidgetView } from "./WidgetView";
import { usePaidAccess } from "./use-paid-access";
import { PaidProductAccess } from "./PaidProductAccess";
import { PaidProductUsage } from "./PaidProductUsage";
import { usePaidUsage } from "./use-paid-usage";
import { PaidReadStatus } from "./use-paid-read";

type SelectionState =
  | { status: "loading" }
  | { status: "ready"; openPayment?: () => boolean }
  | { status: "error"; requestId: string; message?: PurchaseReadRefusal["message"]; sessionRefused?: boolean };

type AccountBillingProps = { userId: string; emailVerified: boolean; initialPurchaseId?: string };

export function AccountBilling(props: AccountBillingProps) {
  return <Cabinet key={`${props.userId}:${props.emailVerified}:${props.initialPurchaseId ?? ""}`} {...props} />;
}

function Cabinet({ userId, emailVerified, initialPurchaseId }: AccountBillingProps) {
  const t = useTranslations("Account.products");
  const b = useTranslations("Billing");
  const p = useTranslations("Purchase");
  const a = useTranslations("Account.products.paid");
  const { begin, cancel } = useSessionOperation();
  const visit = useRef(Symbol());
  const billingSection = useRef<HTMLElement>(null);
  const paymentNotice = useRef<HTMLDivElement>(null);
  const automaticPaymentId = useRef<string | undefined>(undefined);
  const focusBeforeStatusChange = useRef<Element | null>(null);
  const retrySessionButton = useRef<HTMLButtonElement>(null);
  const paymentButton = useRef<HTMLButtonElement>(null);
  const purchaseSelector = useRef<HTMLSelectElement>(null);
  // undefined permits a visible single-purchase default; null explicitly selects account viewing.
  const [selectedId, setSelectedId] = useState<string | null | undefined>(initialPurchaseId);
  const [selectionState, setSelectionState] = useState<SelectionState>({ status: initialPurchaseId && emailVerified ? "loading" : "ready" });
  const sessionRefused = selectionState.status === "error" && selectionState.sessionRefused === true;
  const canRead = emailVerified && !sessionRefused;
  const rememberFocus = useCallback(() => {
    const focused = document.activeElement;
    if (focused !== document.body) focusBeforeStatusChange.current = focused;
  }, []);
  const continueLinkRef = useCallback((link: HTMLAnchorElement | null) => {
    if (!link) return;
    // Capture focus while React detaches the link, before removing it from the DOM.
    return () => {
      if (document.activeElement === link) rememberFocus();
    };
  }, [rememberFocus]);
  const applyRefusal = useCallback(({ httpStatus, message, requestId }: PurchaseReadRefusal) => {
    cancel();
    if (initialPurchaseId) claimPaymentOpening(initialPurchaseId, userId, visit.current)?.();
    const sessionRefused = httpStatus === 401 || httpStatus === 403;
    if (sessionRefused) rememberFocus();
    // A concurrent selection failure cannot restore a refused cabinet session.
    setSelectionState((previous) => previous.status === "error" && previous.sessionRefused
      ? previous : { status: "error", message, requestId, sessionRefused });
  }, [cancel, initialPurchaseId, rememberFocus, userId]);
  const widget = useBillingWidget(userId, emailVerified, applyRefusal);
  const { open: openWidget, close: closeWidget } = widget;
  const handleRefusal = useCallback((refusal: PurchaseReadRefusal) => {
    applyRefusal(refusal);
    if (refusal.httpStatus === 401 || refusal.httpStatus === 403) closeWidget();
  }, [applyRefusal, closeWidget]);
  const purchases = useAccountPurchases(canRead, handleRefusal);
  const { applyStatus } = purchases;
  const paymentWidgetOpen = widget.state.status === WidgetStatus.Open && widget.state.target !== null;
  const paid = usePaidAccess(canRead, handleRefusal, paymentWidgetOpen);
  const usage = usePaidUsage(canRead, handleRefusal);

  useEffect(() => {
    if (!initialPurchaseId || !canRead) return;
    const consumeOpening = claimPaymentOpening(initialPurchaseId, userId, visit.current);
    const operation = begin();
    const requestId = newRequestId();
    async function load(purchaseId: string) {
      if (!operation.token) throw new Error("session_required");
      const readStartedAt = performance.now();
      const result = await purchaseStatus(operation.token, purchaseId, requestId);
      if (operation.isCurrent()) {
        if (result.purchase_intent_id === purchaseId) applyStatus(result, readStartedAt);
        if (!result.scope_held || result.purchase_intent_id !== purchaseId) {
          consumeOpening?.();
          setSelectionState({ status: "error", requestId });
          return;
        }
        if (result.state !== "linked") consumeOpening?.();
        setSelectionState({ status: "ready", openPayment: result.state === "linked" ? consumeOpening : undefined });
      }
    }
    void load(initialPurchaseId).catch((error: unknown) => {
      const refusal = purchaseReadRefusal(error, requestId);
      if (refusal) {
        if (operation.isCurrent()) {
          handleRefusal(refusal);
        } else if (refusal.httpStatus === 401 && operation.isCurrentSession()) {
          reportBillingSessionRefusal(error, refusal.requestId, handleRefusal);
        }
        return;
      }
      if (!operation.isCurrent()) return;
      consumeOpening?.();
      setSelectionState({ status: "error", requestId: safeRequestId(error) || requestId });
    });
    return cancel;
  }, [applyStatus, begin, cancel, canRead, handleRefusal, initialPurchaseId, userId]);

  useEffect(() => subscribeToSessionChanges(() => {
    cancel();
    setSelectedId(null);
    setSelectionState({ status: "error", requestId: "" });
  }), [cancel]);

  const directPurchase = initialPurchaseId ? purchases.findPurchase(initialPurchaseId) : undefined;
  const options = directPurchase
    ? [directPurchase, ...purchases.items.filter((item) => item.purchase_intent_id !== directPurchase.purchase_intent_id)]
    : purchases.items;
  const defaultPurchase = purchases.status === "ready" && !purchases.cursor && purchases.items.length === 1 ? purchases.items[0] : undefined;
  const selection = selectedId === undefined ? defaultPurchase : options.find((item) => item.purchase_intent_id === selectedId);
  const selectionId = selection?.purchase_intent_id;
  const selectionBlocked = selectionState.status !== "ready" || (!!selectedId && !selection);
  const checking = selection?.checking === true;
  const canPay = !selectionBlocked && selection?.state === "linked" && !checking;
  const widgetStatus = widget.state.status;
  const widgetOpen = widgetStatus === WidgetStatus.Open;
  const paymentTarget = "target" in widget.state ? widget.state.target : null;
  const paymentPurchaseId = "purchaseId" in widget.state ? widget.state.purchaseId : undefined;
  const paymentUnavailable = paymentPurchaseId !== undefined && (
    selectionState.status === "error" || selectionId !== paymentPurchaseId || (!checking && selection?.state !== "linked")
  );

  useLayoutEffect(() => {
    if (paymentUnavailable) {
      if (billingSection.current?.contains(document.activeElement)) rememberFocus();
      closeWidget();
      return;
    }
    const focused = focusBeforeStatusChange.current;
    focusBeforeStatusChange.current = null;
    if (
      focused &&
      document.activeElement === document.body &&
      (!focused.isConnected || focused.matches(":disabled"))
    ) {
      const target = sessionRefused ? retrySessionButton.current
        : canPay && !widget.loading ? paymentButton.current : purchaseSelector.current;
      target?.focus();
    }
  });

  useLayoutEffect(() => {
    const purchaseId = automaticPaymentId.current;
    if (!purchaseId || widgetStatus === WidgetStatus.Bootstrapping) return;
    automaticPaymentId.current = undefined;
    const notice = paymentNotice.current;
    if (notice && !paymentUnavailable && paymentTarget?.purchase_intent_id === purchaseId) {
      // The sticky navigation can wrap, so account for its live height.
      const navigationBottom = document.querySelector(".top-nav")?.getBoundingClientRect().bottom ?? 0;
      notice.style.scrollMarginTop = `${Math.max(0, navigationBottom)}px`;
      notice.scrollIntoView({ behavior: "instant", block: "nearest" });
    }
  }, [paymentTarget, paymentUnavailable, widgetStatus]);

  useEffect(() => {
    if (!checking && selectionState.status === "ready" && selectionState.openPayment?.() && canPay && selectionId && selectionId === initialPurchaseId) {
      billingSection.current?.scrollIntoView({ behavior: "instant", block: "start" });
      automaticPaymentId.current = selectionId;
      void openWidget(selectionId);
    }
  }, [canPay, checking, initialPurchaseId, openWidget, selectionId, selectionState]);

  const statusTarget = canRead && !selectionBlocked ? selection : undefined;
  const poll = usePurchaseStatusPoll(
    statusTarget,
    undefined,
    applyStatus,
    handleRefusal,
    {
      enabled: statusTarget !== undefined && (checking || purchaseNeedsStatus(statusTarget)),
      initialDelayMs: checking ? 0 : undefined,
      acceptLateSessionRefusal: true
    }
  );
  const paidOnlyProducts = [...new Set([
    ...(paid.state.status === PaidReadStatus.Ready ? [...paid.state.data.grants, ...paid.state.data.products].map((item) => item.product_id) : []),
    ...(usage.state.status === PaidReadStatus.Ready ? usage.state.data.items.map((item) => item.product_id) : []),
  ])].filter((id) => !purchases.items.some((item) => item.product_id === id));

  function refreshPaid(afterCurrent = false) {
    void paid.refresh(afterCurrent);
    void usage.refresh();
  }

  function choose(id: string) {
    automaticPaymentId.current = undefined;
    cancel();
    widget.close();
    poll.clearPause();
    setSelectedId(id || null);
    setSelectionState({ status: "ready" });
  }

  function manage(id: string) {
    choose(id);
    billingSection.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    void widget.open(id);
  }

  function openSelected() {
    automaticPaymentId.current = undefined;
    // Freeze explicit account viewing if inventory finishes after this click.
    setSelectedId(selection?.purchase_intent_id ?? null);
    void widget.open(selection?.purchase_intent_id);
  }

  return <>
    <section ref={billingSection} id="billing" className="account-products-panel account-billing-panel" aria-label={b("title")}>
      <h2>{b("title")}</h2>
      <p className="card-copy">{b("description")}</p>
      {!emailVerified && <p className="card-copy">{b("verificationRequired")}</p>}
      {emailVerified && <div className="billing-selection">
        {!sessionRefused && <>
          <label htmlFor="billing-purchase">{b("selectedPurchase")}</label>
          <select ref={purchaseSelector} id="billing-purchase" value={selection?.purchase_intent_id ?? selectedId ?? ""} disabled={selectionState.status === "loading"} onChange={(event) => choose(event.target.value)}>
            <option value="">{b("accountView")}</option>
            {selectionBlocked && selectedId && !selection && <option value={selectedId}>{selectionState.status === "loading" ? p("loading") : b("selectionUnavailable")}</option>}
            {options.map((item) => <option key={item.purchase_intent_id} value={item.purchase_intent_id}>{b("purchaseOption", { product: item.product_id, id: item.purchase_intent_id })}</option>)}
          </select>
        </>}
        {selectionState.status === "loading" && <p role="status">{p("loading")}</p>}
        {selectionBlocked && selectionState.status !== "loading" && <div className="notice error" role="alert">
          <p>{b((selectionState.status === "error" ? selectionState.message : undefined) ?? "selectionUnavailable")}</p>
          {selectionState.status === "error" && selectionState.requestId && <p>{b("requestId", { id: selectionState.requestId })}</p>}
          {sessionRefused && <button ref={retrySessionButton} className="btn-secondary" type="button" onClick={() => window.location.reload()}>{p("retry")}</button>}
        </div>}
        {!sessionRefused && selection && <p className="billing-selected-product">{b("selectedProduct", { product: selection.product_id })}</p>}
        {!selectionBlocked && checking && !poll.paused && <p role="status">{p("loading")}</p>}
        {poll.paused && <p role="status">{p("statusPollingPaused")}</p>}
        {!selectionBlocked && selection && !canPay && <p>{!checking && b("preparationRequired")} <Link ref={continueLinkRef} href={`/products/${encodeURIComponent(selection.product_id)}`}>{p("continue")}</Link></p>}
      </div>}
      <div aria-live="polite">
        {paymentTarget && <div ref={paymentNotice} className="notice">
          <p>{b("paymentTarget", { agreement: paymentTarget.agreement_reference, seller: paymentTarget.seller_reference })}</p>
          <p>{b("paymentTargetNote")}</p>
        </div>}
      </div>
      <button ref={paymentButton} className="btn-primary" type="button" aria-describedby={widgetOpen ? "billing-refresh-hint" : undefined} disabled={!emailVerified || selectionBlocked || (!!selection && !canPay) || widget.loading} onClick={openSelected}>
        {widget.loading ? b("loading") : widgetOpen ? b("refresh") : canPay ? b("pay") : b("open")}
      </button>
      {widgetOpen && <p id="billing-refresh-hint" className="card-copy">{b("refreshHint")}</p>}
      <WidgetView widget={widget} onClose={() => refreshPaid(true)} />
    </section>
    {!sessionRefused && <section className="account-products-panel" aria-label={t("title")}>
      <div className="account-products-heading">
        <h2>{t("title")}</h2>
        <p className="card-copy">{t("description")}</p>
        <div className="account-products-actions">
          <Link className="btn-secondary" href="/products">{t("allProducts")}</Link>
          {emailVerified && <button className="btn-secondary" type="button" onClick={() => refreshPaid()} disabled={paid.state.status === PaidReadStatus.Loading}>{a("refresh")}</button>}
        </div>
      </div>
      {emailVerified && paid.state.status === PaidReadStatus.Unavailable && <div className="notice error" role="alert">
        <p>{a(paid.state.deadlinePending ? "deadlinePending" : "unavailable")}</p>
        {paid.state.requestId && <p>{b("requestId", { id: paid.state.requestId })}</p>}
      </div>}
      {emailVerified && paid.state.status === PaidReadStatus.Ready && paid.state.data.evidence_complete && !paid.state.data.products.length && !paid.state.data.grants.length && <p className="card-copy">{a("empty")}</p>}
      {purchases.status === "loading" && <p role="status">{t("loading")}</p>}
      {purchases.status === "error" && <div className="notice error" role="alert">
        <p>{t("unavailable")}</p>
        {purchases.requestId && <p>{b("requestId", { id: purchases.requestId })}</p>}
        <button className="btn-secondary" type="button" onClick={() => void purchases.load(purchases.cursor ?? undefined)}>{p("retry")}</button>
      </div>}
      {purchases.status === "ready" && !purchases.items.length && <p className="card-copy">{t("empty")}</p>}
      <div className="account-products-grid">
        {purchases.items.map((item) => <article className="account-product-card" key={item.purchase_intent_id}>
          <div className="account-product-heading"><h3><Link href={`/products/${encodeURIComponent(item.product_id)}`}>{item.product_id}</Link></h3></div>
          {!item.checking && <p className="card-copy">{item.state === "linked" ? t("prepared") : t("pending")}</p>}
          {emailVerified && <PaidProductAccess productId={item.product_id} paid={paid} />}
          {emailVerified && <PaidProductUsage productId={item.product_id} usage={usage} />}
          <div className="account-product-actions">
            <Link className="btn-secondary" href={`/products/${encodeURIComponent(item.product_id)}`}>{t("detailAction")}</Link>
            {item.state === "linked" && !item.checking
              ? <button className="btn-secondary" type="button" disabled={!emailVerified} onClick={() => manage(item.purchase_intent_id)}>{p("manage")}</button>
              : <Link ref={item.purchase_intent_id === selectionId ? continueLinkRef : undefined} className="btn-secondary" href={`/products/${encodeURIComponent(item.product_id)}`}>{p("continue")}</Link>}
          </div>
        </article>)}
        {paidOnlyProducts.map((id) => <article className="account-product-card" key={id}>
          <div className="account-product-heading"><h3><Link href={`/products/${encodeURIComponent(id)}`}>{id}</Link></h3></div>
          <PaidProductAccess productId={id} paid={paid} />
          <PaidProductUsage productId={id} usage={usage} />
          <Link className="btn-secondary" href={`/products/${encodeURIComponent(id)}`}>{t("detailAction")}</Link>
        </article>)}
      </div>
      {purchases.cursor && <button className="btn-secondary" type="button" disabled={purchases.status === "loading"} onClick={() => void purchases.load(purchases.cursor!)}>{t("loadMore")}</button>}
    </section>}
  </>;
}
