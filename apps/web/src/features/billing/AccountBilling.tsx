"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import type { PurchaseIntentResponse } from "@/generated/api-contracts/types.gen";
import { Link } from "@/i18n/navigation";
import { purchaseStatus } from "@/shared/api/purchases";
import { subscribeToSessionChanges, useSessionOperation } from "@/shared/session/use-session-operation";
import { newRequestId, safeRequestId } from "./errors";
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

type SelectionState = { status: "loading" | "ready" } | { status: "error"; requestId: string };

type AccountBillingProps = { userId: string; emailVerified: boolean; initialPurchaseId?: string };

export function AccountBilling(props: AccountBillingProps) {
  return <Cabinet key={`${props.userId}:${props.emailVerified}:${props.initialPurchaseId ?? ""}`} {...props} />;
}

function Cabinet({ userId, emailVerified, initialPurchaseId }: AccountBillingProps) {
  const t = useTranslations("Account.products");
  const b = useTranslations("Billing");
  const p = useTranslations("Purchase");
  const a = useTranslations("Account.products.paid");
  const purchases = useAccountPurchases(emailVerified);
  const { applyStatus } = purchases;
  const paid = usePaidAccess(emailVerified);
  const usage = usePaidUsage(emailVerified);
  const widget = useBillingWidget(userId, emailVerified);
  const openWidget = widget.open;
  const { begin, cancel } = useSessionOperation();
  const visit = useRef(Symbol());
  // undefined permits a visible single-purchase default; null explicitly selects account viewing.
  const [selectedId, setSelectedId] = useState<string | null | undefined>(initialPurchaseId);
  const [deepPurchase, setDeepPurchase] = useState<PurchaseIntentResponse | null>(null);
  const [selectionState, setSelectionState] = useState<SelectionState>({ status: initialPurchaseId && emailVerified ? "loading" : "ready" });

  useEffect(() => {
    if (!initialPurchaseId || !emailVerified) return;
    const consumeOpening = claimPaymentOpening(initialPurchaseId, userId, visit.current);
    const operation = begin();
    const requestId = newRequestId();
    async function load(purchaseId: string) {
      if (!operation.token) throw new Error("session_required");
      const result = await purchaseStatus(operation.token, purchaseId, requestId);
      if (operation.isCurrent()) {
        const openRequested = consumeOpening?.();
        if (!result.scope_held || result.purchase_intent_id !== purchaseId) {
          setSelectionState({ status: "error", requestId });
          return;
        }
        applyStatus(result);
        setDeepPurchase(result);
        setSelectionState({ status: "ready" });
        if (openRequested && result.state === "linked") void openWidget(result.purchase_intent_id);
      }
    }
    void load(initialPurchaseId).catch((error: unknown) => {
      if (!operation.isCurrent()) return;
      consumeOpening?.();
      setSelectionState({ status: "error", requestId: safeRequestId(error) || requestId });
    });
    return cancel;
  }, [applyStatus, begin, cancel, emailVerified, initialPurchaseId, openWidget, userId]);

  useEffect(() => subscribeToSessionChanges(() => {
    cancel();
    setDeepPurchase(null);
    setSelectedId(null);
    setSelectionState({ status: "error", requestId: "" });
  }), [cancel]);

  const options = deepPurchase
    ? [deepPurchase, ...purchases.items.filter((item) => item.purchase_intent_id !== deepPurchase.purchase_intent_id)]
    : purchases.items;
  const defaultPurchase = purchases.status === "ready" && !purchases.cursor && purchases.items.length === 1 ? purchases.items[0] : undefined;
  const selection = selectedId === undefined ? defaultPurchase : options.find((item) => item.purchase_intent_id === selectedId);
  const selectionBlocked = selectionState.status !== "ready" || (!!selectedId && !selection);
  const canPay = selection?.state === "linked";
  const widgetOpen = widget.state.status === WidgetStatus.Open;

  const poll = usePurchaseStatusPoll(
    emailVerified && !selectionBlocked && selection && purchaseNeedsStatus(selection) ? selection : undefined,
    undefined,
    (saved) => {
      applyStatus(saved);
      if (deepPurchase?.purchase_intent_id === saved.purchase_intent_id) setDeepPurchase(saved.scope_held ? saved : null);
    }
  );
  const paidOnlyProducts = [...new Set([
    ...(paid.state.status === PaidReadStatus.Ready ? [...paid.state.data.grants, ...paid.state.data.products].map((item) => item.product_id) : []),
    ...(usage.state.status === PaidReadStatus.Ready ? usage.state.data.items.map((item) => item.product_id) : []),
  ])].filter((id) => !purchases.items.some((item) => item.product_id === id));

  function refreshPaid() {
    void paid.refresh();
    void usage.refresh();
  }

  function choose(id: string) {
    cancel();
    widget.close();
    poll.clearPause();
    setSelectedId(id || null);
    setSelectionState({ status: "ready" });
  }

  function manage(id: string) {
    choose(id);
    document.getElementById("billing")?.scrollIntoView({ behavior: "smooth", block: "start" });
    void widget.open(id);
  }

  function openSelected() {
    // Freeze explicit account viewing if inventory finishes after this click.
    setSelectedId(selection?.purchase_intent_id ?? null);
    void widget.open(selection?.purchase_intent_id);
  }

  return <>
    <section id="billing" className="account-products-panel account-billing-panel" aria-label={b("title")}>
      <h2>{b("title")}</h2>
      <p className="card-copy">{b("description")}</p>
      {!emailVerified && <p className="card-copy">{b("verificationRequired")}</p>}
      {emailVerified && <div className="billing-selection">
        <label htmlFor="billing-purchase">{b("selectedPurchase")}</label>
        <select id="billing-purchase" value={selection?.purchase_intent_id ?? selectedId ?? ""} disabled={selectionState.status === "loading"} onChange={(event) => choose(event.target.value)}>
          <option value="">{b("accountView")}</option>
          {selectionBlocked && selectedId && !selection && <option value={selectedId}>{selectionState.status === "loading" ? p("loading") : b("selectionUnavailable")}</option>}
          {options.map((item) => <option key={item.purchase_intent_id} value={item.purchase_intent_id}>{b("purchaseOption", { product: item.product_id, id: item.purchase_intent_id })}</option>)}
        </select>
        {selectionState.status === "loading" && <p role="status">{p("loading")}</p>}
        {selectionBlocked && selectionState.status !== "loading" && <div className="notice error" role="alert"><p>{b("selectionUnavailable")}</p>{selectionState.status === "error" && selectionState.requestId && <p>{b("requestId", { id: selectionState.requestId })}</p>}</div>}
        {selection && <p className="billing-selected-product">{b("selectedProduct", { product: selection.product_id })}</p>}
        {poll.paused && <p role="status">{p("statusPollingPaused")}</p>}
        {selection && !canPay && <p>{b("preparationRequired")} <Link href={`/products/${encodeURIComponent(selection.product_id)}`}>{p("continue")}</Link></p>}
      </div>}
      <button className="btn-primary" type="button" aria-describedby={widgetOpen ? "billing-refresh-hint" : undefined} disabled={!emailVerified || selectionBlocked || (!!selection && !canPay) || widget.loading} onClick={openSelected}>
        {widget.loading ? b("loading") : widgetOpen ? b("refresh") : canPay ? b("pay") : b("open")}
      </button>
      {widgetOpen && <p id="billing-refresh-hint" className="card-copy">{b("refreshHint")}</p>}
      <WidgetView widget={widget} onClose={refreshPaid} />
    </section>
    <section className="account-products-panel" aria-label={t("title")}>
      <div className="account-products-heading">
        <h2>{t("title")}</h2>
        <p className="card-copy">{t("description")}</p>
        <div className="account-products-actions">
          <Link className="btn-secondary" href="/products">{t("allProducts")}</Link>
          {emailVerified && <button className="btn-secondary" type="button" onClick={refreshPaid} disabled={paid.state.status === PaidReadStatus.Loading}>{a("refresh")}</button>}
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
          <p className="card-copy">{item.state === "linked" ? t("prepared") : t("pending")}</p>
          {emailVerified && <PaidProductAccess productId={item.product_id} paid={paid} />}
          {emailVerified && <PaidProductUsage productId={item.product_id} usage={usage} />}
          <div className="account-product-actions">
            <Link className="btn-secondary" href={`/products/${encodeURIComponent(item.product_id)}`}>{t("detailAction")}</Link>
            {item.state === "linked"
              ? <button className="btn-secondary" type="button" disabled={!emailVerified} onClick={() => manage(item.purchase_intent_id)}>{p("manage")}</button>
              : <Link className="btn-secondary" href={`/products/${encodeURIComponent(item.product_id)}`}>{p("continue")}</Link>}
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
    </section>
  </>;
}
