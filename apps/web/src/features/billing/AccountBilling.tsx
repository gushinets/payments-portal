"use client";

import { useEffect, useEffectEvent, useState } from "react";
import { useTranslations } from "next-intl";
import type { AccountPurchaseResponse, PurchaseIntentResponse } from "@/generated/api-contracts/types.gen";
import { Link } from "@/i18n/navigation";
import { purchaseStatus } from "@/shared/api/purchases";
import { subscribeToSessionChanges, useSessionOperation } from "@/shared/session/use-session-operation";
import { newRequestId, safeRequestId } from "./errors";
import { useAccountPurchases } from "./use-account-purchases";
import { useBillingWidget } from "./use-billing-widget";
import { WidgetView } from "./WidgetView";
import { usePaidAccess } from "./use-paid-access";
import { PaidProductAccess } from "./PaidProductAccess";
import { PaidProductUsage } from "./PaidProductUsage";
import { usePaidUsage } from "./use-paid-usage";
import { PaidReadStatus } from "./use-paid-read";
import { isResolvedPurchase } from "./purchase-state";

type DetailStatus = { status: "loading" | "ready" | "session-ended" } | { status: "error"; requestId: string };
type ListEvidence = AccountPurchaseResponse | AccountPurchaseResponse[];

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
  const paid = usePaidAccess(emailVerified);
  const usage = usePaidUsage(emailVerified);
  const widget = useBillingWidget(userId, emailVerified);
  const { begin, cancel } = useSessionOperation();
  // undefined permits a visible single-purchase default; null explicitly selects account viewing.
  const [selectedId, setSelectedId] = useState<string | null | undefined>(initialPurchaseId);
  const [detail, setDetail] = useState<{ purchase: PurchaseIntentResponse; checkedListEvidence?: ListEvidence } | null>(null);
  const deepPurchase = detail?.purchase;
  const listed = purchases.items.find((item) => item.purchase_intent_id === initialPurchaseId);
  const listEvidence = listed ?? (purchases.status === "ready" && !purchases.cursor ? purchases.items : undefined);
  // Neither concurrent response has a revision. Resolve a disagreement with one later status read.
  const disagreement = deepPurchase?.scope_held && deepPurchase.state !== listed?.state ? listEvidence : undefined;
  const checkAgainst = disagreement ?? detail?.checkedListEvidence;
  const disputed = checkAgainst !== detail?.checkedListEvidence;
  const [detailStatus, setDetailStatus] = useState<DetailStatus>({ status: initialPurchaseId && emailVerified ? "loading" : "ready" });

  const sessionEnded = detailStatus.status === "session-ended";
  const closeRestrictedWidget = useEffectEvent(() => {
    if (selectedId === initialPurchaseId) widget.close();
  });

  useEffect(() => {
    if (!initialPurchaseId || !emailVerified || sessionEnded) return;
    const operation = begin();
    const requestId = newRequestId();
    async function load() {
      if (!operation.token) throw new Error("session_required");
      const result = await purchaseStatus(operation.token, initialPurchaseId!, requestId);
      if (operation.isCurrent()) {
        if (!result.scope_held && !isResolvedPurchase(result.state)) { setDetailStatus({ status: "error", requestId }); return; }
        if (checkAgainst && (!result.scope_held || result.state !== "linked")) closeRestrictedWidget();
        setDetail({ purchase: result, checkedListEvidence: checkAgainst });
        setDetailStatus({ status: "ready" });
      }
    }
    void load().catch((error: unknown) => { if (operation.isCurrent()) setDetailStatus({ status: "error", requestId: safeRequestId(error) || requestId }); });
    return cancel;
  }, [begin, cancel, emailVerified, initialPurchaseId, sessionEnded, checkAgainst]);

  useEffect(() => subscribeToSessionChanges(() => {
    cancel();
    setDetail(null);
    setSelectedId(null);
    setDetailStatus({ status: "session-ended" });
  }), [cancel]);

  const releasedDeepPurchase = deepPurchase && !deepPurchase.scope_held ? deepPurchase : null;
  const activeItems = purchases.items
    .filter((item) => item.purchase_intent_id !== releasedDeepPurchase?.purchase_intent_id)
    .map((item) => item.purchase_intent_id === deepPurchase?.purchase_intent_id ? { ...item, state: deepPurchase.state } : item);
  const options = deepPurchase && !activeItems.some((item) => item.purchase_intent_id === deepPurchase.purchase_intent_id)
    ? [deepPurchase, ...activeItems] : activeItems;
  const defaultPurchase = purchases.status === "ready" && !purchases.cursor && activeItems.length === 1 ? activeItems[0] : undefined;
  const selection = selectedId === undefined ? defaultPurchase : options.find((item) => item.purchase_intent_id === selectedId);
  const checkingDetail = detailStatus.status === "loading" || (disputed && detailStatus.status === "ready");
  const selectedDeep = !!selectedId && selectedId === initialPurchaseId;
  const checkingSelection = selectedDeep && checkingDetail;
  const selectionBlocked = sessionEnded || (selectedDeep && (checkingDetail || detailStatus.status === "error")) || (!!selectedId && !selection);
  const widgetSuspended = selectedDeep && disputed;
  const released = selection && releasedDeepPurchase?.purchase_intent_id === selection.purchase_intent_id;
  const canPay = selection?.state === "linked" && !released;
  const paidOnlyProducts = [...new Set([
    ...(paid.state.status === PaidReadStatus.Ready ? [...paid.state.data.grants, ...paid.state.data.products].map((item) => item.product_id) : []),
    ...(usage.state.status === PaidReadStatus.Ready ? usage.state.data.items.map((item) => item.product_id) : []),
  ])].filter((id) => !activeItems.some((item) => item.product_id === id));

  function refreshPaid() {
    void paid.refresh();
    void usage.refresh();
  }

  function choose(id: string) {
    widget.close();
    setSelectedId(id || null);
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
        <select id="billing-purchase" value={selection?.purchase_intent_id ?? selectedId ?? ""} disabled={checkingSelection} onChange={(event) => choose(event.target.value)}>
          <option value="">{b("accountView")}</option>
          {selectionBlocked && selectedId && !selection && <option value={selectedId}>{checkingSelection ? p("loading") : b("selectionUnavailable")}</option>}
          {options.map((item) => <option key={item.purchase_intent_id} value={item.purchase_intent_id}>{b("purchaseOption", { product: item.product_id, id: item.purchase_intent_id })}</option>)}
        </select>
        {checkingSelection && <p role="status">{p("loading")}</p>}
        {selectionBlocked && !checkingSelection && <div className="notice error" role="alert"><p>{b("selectionUnavailable")}</p>{detailStatus.status === "error" && detailStatus.requestId && <p>{b("requestId", { id: detailStatus.requestId })}</p>}</div>}
        {selection && <p className="billing-selected-product">{b("selectedProduct", { product: selection.product_id })}</p>}
        {selection && released && <>
          <p role="status">{p(`states.${selection.state}`)}</p>
          <p>{p("resolvedNext")} <Link href={`/products/${encodeURIComponent(selection.product_id)}`}>{p("buy")}</Link></p>
        </>}
        {selection && !canPay && !released && <p>{b("preparationRequired")} <Link href={`/products/${encodeURIComponent(selection.product_id)}`}>{p("continue")}</Link></p>}
      </div>}
      <button className="btn-primary" type="button" aria-describedby={widget.state.status === "open" && !widgetSuspended ? "billing-refresh-hint" : undefined} disabled={!emailVerified || selectionBlocked || (!!selection && !canPay) || widget.state.status === "loading"} onClick={openSelected}>
        {widget.state.status === "loading" ? b("loading") : widget.state.status === "open" ? b("refresh") : b("open")}
      </button>
      {widget.state.status === "open" && !widgetSuspended && <p id="billing-refresh-hint" className="card-copy">{b("refreshHint")}</p>}
      <div hidden={widgetSuspended}><WidgetView widget={widget} onClose={refreshPaid} /></div>
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
      {purchases.status === "ready" && !activeItems.length && <p className="card-copy">{t("empty")}</p>}
      <div className="account-products-grid">
        {activeItems.map((item) => <article className="account-product-card" key={item.purchase_intent_id}>
          <div className="account-product-heading"><h3><Link href={`/products/${encodeURIComponent(item.product_id)}`}>{item.product_id}</Link></h3></div>
          <p className="card-copy">{item.state === "linked" ? t("prepared") : t("pending")}</p>
          {emailVerified && <PaidProductAccess productId={item.product_id} paid={paid} />}
          {emailVerified && <PaidProductUsage productId={item.product_id} usage={usage} />}
          <div className="account-product-actions">
            <Link className="btn-secondary" href={`/products/${encodeURIComponent(item.product_id)}`}>{t("detailAction")}</Link>
            {item.state === "linked"
              ? <button className="btn-secondary" type="button" disabled={!emailVerified || (item.purchase_intent_id === initialPurchaseId && (checkingDetail || detailStatus.status !== "ready"))} onClick={() => manage(item.purchase_intent_id)}>{p("manage")}</button>
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
