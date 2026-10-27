"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import type { WidgetPaymentTarget } from "@/generated/api-contracts/types.gen";
import { bootstrapWidget } from "@/shared/api/billing";
import { subscribeToSessionChanges, useSessionOperation } from "@/shared/session/use-session-operation";
import { billingErrorKey, newRequestId, safeRequestId, type BillingErrorKey } from "./errors";
import { mountOfficialWidget } from "./official-widget-sdk";

type WidgetState =
  | { status: "closed" | "loading" }
  | { status: "open"; target: WidgetPaymentTarget | null }
  | { status: "error"; message: BillingErrorKey; requestId: string };

// A new presentation destroys the previous host, including an account-only JWT.
const widgetOpeningEvent = "anytoolai_billing_widget_opening";

export function useBillingWidget(userId: string, emailVerified: boolean) {
  const t = useTranslations("Billing");
  const { begin, cancel } = useSessionOperation();
  const [state, setState] = useState<WidgetState>({ status: "closed" });
  const node = useRef<HTMLDivElement>(null);
  const dispose = useRef<(() => void) | undefined>(undefined);
  const opening = useRef(false);
  const owner = useRef(Symbol());
  const attachNode = useCallback((element: HTMLDivElement | null) => { node.current = element; }, []);

  useEffect(() => {
    const clear = () => {
      cancel();
      dispose.current?.();
      dispose.current = undefined;
      opening.current = false;
      setState({ status: "closed" });
    };
    const otherOpening = (event: Event) => {
      if (event instanceof CustomEvent && event.detail !== owner.current) clear();
    };
    const unsubscribe = subscribeToSessionChanges(clear);
    window.addEventListener(widgetOpeningEvent, otherOpening);
    return () => {
      unsubscribe();
      window.removeEventListener(widgetOpeningEvent, otherOpening);
      cancel();
      dispose.current?.();
      dispose.current = undefined;
      opening.current = false;
    };
  }, [userId, emailVerified, cancel]);

  async function open(purchaseId?: string) {
    if (!emailVerified || opening.current) return;
    window.dispatchEvent(new CustomEvent(widgetOpeningEvent, { detail: owner.current }));
    opening.current = true;
    dispose.current?.();
    dispose.current = undefined;
    const operation = begin();
    const correlationId = newRequestId();
    setState({ status: "loading" });
    try {
      if (!operation.token) {
        setState({ status: "error", message: "session", requestId: "" });
        return;
      }
      const response = purchaseId
        ? await bootstrapWidget(operation.token, correlationId, purchaseId)
        : await bootstrapWidget(operation.token, correlationId);
      if (!operation.isCurrent() || !node.current) {
        response.credential = "";
        if (operation.isLatest()) setState({ status: "error", message: "session", requestId: correlationId });
        return;
      }
      const id = response.request_id || correlationId;
      const sdkFailure = () => {
        if (operation.isCurrent()) {
          dispose.current?.();
          dispose.current = undefined;
          setState({ status: "error", message: "sdk", requestId: id });
        }
      };
      try {
        if (purchaseId ? response.presentation !== "payment" || response.payment_target?.purchase_intent_id !== purchaseId : response.presentation !== "account") {
          throw new Error("widget_target_refused");
        }
        dispose.current = mountOfficialWidget(node.current, response, t("frameTitle"), operation.isCurrent, sdkFailure);
        setState({ status: "open", target: response.payment_target ?? null });
      } catch {
        response.credential = "";
        sdkFailure();
      }
    } catch (error) {
      if (operation.isCurrent()) setState({ status: "error", message: billingErrorKey(error), requestId: safeRequestId(error) || correlationId });
    } finally {
      if (operation.isLatest()) opening.current = false;
    }
  }

  function close() {
    cancel();
    dispose.current?.();
    dispose.current = undefined;
    opening.current = false;
    setState({ status: "closed" });
  }

  return { state, attachNode, open, close };
}
