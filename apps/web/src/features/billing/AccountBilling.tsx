"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import type { PurchaseIntentResponse } from "@/generated/api-contracts/types.gen";
import { Link } from "@/i18n/navigation";
import { purchaseStatus } from "@/shared/api/purchases";
import { subscribeToSessionChanges, useSessionOperation } from "@/shared/session/use-session-operation";
import { newRequestId } from "./errors";
import { useAccountPurchases } from "./use-account-purchases";
import { useBillingWidget } from "./use-billing-widget";
import { WidgetView } from "./WidgetView";

type AccountBillingProps = { userId: string; emailVerified: boolean; initialPurchaseId?: string };

export function AccountBilling(props: AccountBillingProps) {
  return <Cabinet key={`${props.userId}:${props.emailVerified}:${props.initialPurchaseId ?? ""}`} {...props} />;
}

function Cabinet({ userId, emailVerified, initialPurchaseId }: AccountBillingProps) {
  const t = useTranslations("Account.products");
  const b = useTranslations("Billing");
  const p = useTranslations("Purchase");
  const purchases = useAccountPurchases(emailVerified);
  const widget = useBillingWidget(userId, emailVerified);
  const { begin, cancel } = useSessionOperation();
  // undefined permits a visible single-purchase default; null explicitly selects account viewing.
  const [selectedId, setSelectedId] = useState<string | null | undefined>(initialPurchaseId);
  const [deepPurchase, setDeepPurchase] = useState<PurchaseIntentResponse | null>(null);
  const [selectionStatus, setSelectionStatus] = useState<"loading" | "ready" | "error">(initialPurchaseId && emailVerified ? "loading" : "ready");

  useEffect(() => {
    if (!initialPurchaseId || !emailVerified) return;
    const operation = begin();
    async function load() {
      if (!operation.token) throw new Error("session_required");
      const result = await purchaseStatus(operation.token, initialPurchaseId!, newRequestId());
      if (operation.isCurrent()) {
        if (!result.scope_held) { setSelectionStatus("error"); return; }
        setDeepPurchase(result);
        setSelectionStatus("ready");
      }
    }
    void load().catch(() => { if (operation.isCurrent()) setSelectionStatus("error"); });
    return cancel;
  }, [begin, cancel, emailVerified, initialPurchaseId]);

  useEffect(() => subscribeToSessionChanges(() => {
    cancel();
    setDeepPurchase(null);
    setSelectedId(null);
    setSelectionStatus("error");
  }), [cancel]);

  const options = deepPurchase && !purchases.items.some((item) => item.purchase_intent_id === deepPurchase.purchase_intent_id)
    ? [deepPurchase, ...purchases.items] : purchases.items;
  const defaultPurchase = purchases.status === "ready" && !purchases.cursor && purchases.items.length === 1 ? purchases.items[0] : undefined;
  const selection = selectedId === undefined ? defaultPurchase : options.find((item) => item.purchase_intent_id === selectedId);
  const selectionBlocked = selectionStatus !== "ready" || (!!selectedId && !selection);
  const canPay = selection?.state === "linked";

  function choose(id: string) {
    cancel();
    widget.close();
    setSelectedId(id || null);
    setSelectionStatus("ready");
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
        <select id="billing-purchase" value={selection?.purchase_intent_id ?? selectedId ?? ""} disabled={selectionStatus === "loading"} onChange={(event) => choose(event.target.value)}>
          <option value="">{b("accountView")}</option>
          {selectionBlocked && selectedId && !selection && <option value={selectedId}>{b("selectionUnavailable")}</option>}
          {options.map((item) => <option key={item.purchase_intent_id} value={item.purchase_intent_id}>{b("purchaseOption", { product: item.product_id, id: item.purchase_intent_id })}</option>)}
        </select>
        {selectionStatus === "loading" && <p role="status">{p("loading")}</p>}
        {selectionBlocked && selectionStatus !== "loading" && <p className="notice error" role="alert">{b("selectionUnavailable")}</p>}
        {selection && <p className="billing-selected-product">{b("selectedProduct", { product: selection.product_id })}</p>}
        {selection && !canPay && <p>{b("preparationRequired")} <Link href={`/products/${encodeURIComponent(selection.product_id)}`}>{p("continue")}</Link></p>}
      </div>}
      <button className="btn-primary" type="button" aria-describedby={widget.state.status === "open" ? "billing-refresh-hint" : undefined} disabled={!emailVerified || selectionBlocked || (!!selection && !canPay) || widget.state.status === "loading"} onClick={openSelected}>
        {widget.state.status === "loading" ? b("loading") : widget.state.status === "open" ? b("refresh") : b("open")}
      </button>
      {widget.state.status === "open" && <p id="billing-refresh-hint" className="card-copy">{b("refreshHint")}</p>}
      <WidgetView widget={widget} />
    </section>
    <section className="account-products-panel" aria-label={t("title")}>
      <div className="account-products-heading">
        <h2>{t("title")}</h2>
        <p className="card-copy">{t("description")}</p>
        <Link className="btn-secondary" href="/products">{t("allProducts")}</Link>
      </div>
      {purchases.status === "loading" && <p role="status">{t("loading")}</p>}
      {purchases.status === "error" && <div className="notice error" role="alert">
        <p>{t("unavailable")}</p>
        <button className="btn-secondary" type="button" onClick={() => void purchases.load(purchases.cursor ?? undefined)}>{p("retry")}</button>
      </div>}
      {purchases.status === "ready" && !purchases.items.length && <p className="card-copy">{t("empty")}</p>}
      <div className="account-products-grid">
        {purchases.items.map((item) => <article className="account-product-card" key={item.purchase_intent_id}>
          <div className="account-product-heading"><h3><Link href={`/products/${encodeURIComponent(item.product_id)}`}>{item.product_id}</Link></h3></div>
          <p className="card-copy">{item.state === "linked" ? t("prepared") : t("pending")}</p>
          <div className="account-product-actions">
            <Link className="btn-secondary" href={`/products/${encodeURIComponent(item.product_id)}`}>{t("detailAction")}</Link>
            {item.state === "linked"
              ? <button className="btn-secondary" type="button" disabled={!emailVerified} onClick={() => manage(item.purchase_intent_id)}>{p("manage")}</button>
              : <Link className="btn-secondary" href={`/products/${encodeURIComponent(item.product_id)}`}>{p("continue")}</Link>}
          </div>
        </article>)}
      </div>
      {purchases.cursor && <button className="btn-secondary" type="button" disabled={purchases.status === "loading"} onClick={() => void purchases.load(purchases.cursor!)}>{t("loadMore")}</button>}
    </section>
  </>;
}
