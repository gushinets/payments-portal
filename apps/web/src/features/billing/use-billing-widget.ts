"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import type { WidgetPaymentTarget } from "@/generated/api-contracts/types.gen";
import { bootstrapWidget } from "@/shared/api/billing";
import { subscribeToSessionChanges, useSessionOperation } from "@/shared/session/use-session-operation";
import { billingErrorKey, newRequestId, safeRequestId, type BillingErrorKey } from "./errors";
import { mountOfficialWidget } from "./official-widget-sdk";
import { reportBillingWidgetFailure, type WidgetFailureReason } from "@/shared/observability/sentry";

export const WidgetStatus = {
  Closed: "closed",
  Bootstrapping: "bootstrapping",
  Rendering: "rendering",
  Open: "open",
  Error: "error"
} as const;

type WidgetState =
  | { status: typeof WidgetStatus.Closed | typeof WidgetStatus.Bootstrapping }
  | { status: typeof WidgetStatus.Rendering | typeof WidgetStatus.Open; target: WidgetPaymentTarget | null }
  | { status: typeof WidgetStatus.Error; message: BillingErrorKey; requestId: string };

// A new presentation destroys the previous host, including an account-only JWT.
const widgetOpeningEvent = "anytoolai_billing_widget_opening";

export function useBillingWidget(userId: string, emailVerified: boolean) {
  const t = useTranslations("Billing");
  const { begin, cancel } = useSessionOperation();
  const [state, setState] = useState<WidgetState>({ status: WidgetStatus.Closed });
  const node = useRef<HTMLDivElement>(null);
  const dispose = useRef<(() => void) | undefined>(undefined);
  const opening = useRef(false);
  const owner = useRef(Symbol());
  const attachNode = useCallback((element: HTMLDivElement | null) => { node.current = element; }, []);

  const close = useCallback(() => {
    cancel();
    dispose.current?.();
    dispose.current = undefined;
    opening.current = false;
    setState({ status: WidgetStatus.Closed });
  }, [cancel]);

  useEffect(() => {
    const otherOpening = (event: Event) => {
      if (event instanceof CustomEvent && event.detail !== owner.current) close();
    };
    const unsubscribe = subscribeToSessionChanges(close);
    window.addEventListener(widgetOpeningEvent, otherOpening);
    return () => {
      unsubscribe();
      window.removeEventListener(widgetOpeningEvent, otherOpening);
      cancel();
      dispose.current?.();
      dispose.current = undefined;
      opening.current = false;
    };
  }, [userId, emailVerified, cancel, close]);

  const open = useCallback(async (purchaseId?: string) => {
    if (!emailVerified || opening.current) return;
    window.dispatchEvent(new CustomEvent(widgetOpeningEvent, { detail: owner.current }));
    opening.current = true;
    dispose.current?.();
    dispose.current = undefined;
    const operation = begin();
    const correlationId = newRequestId();
    setState({ status: WidgetStatus.Bootstrapping });
    if (!operation.token) {
      opening.current = false;
      setState({ status: WidgetStatus.Error, message: "session", requestId: "" });
      return;
    }
    try {
      const response = purchaseId
        ? await bootstrapWidget(operation.token, correlationId, purchaseId)
        : await bootstrapWidget(operation.token, correlationId);
      if (!operation.isCurrent() || !node.current) {
        response.credential = "";
        if (operation.isLatest()) {
          opening.current = false;
          setState({ status: WidgetStatus.Error, message: "session", requestId: correlationId });
        }
        return;
      }
      const id = response.request_id || correlationId;
      const target = response.payment_target ?? null;
      let failureReported = false;
      const sdkFailure = (reason: WidgetFailureReason = "sdk_failed") => {
        if (operation.isCurrent() && !failureReported) {
          failureReported = true;
          opening.current = false;
          dispose.current?.();
          dispose.current = undefined;
          reportBillingWidgetFailure(id, reason);
          setState({ status: WidgetStatus.Error, message: "sdk", requestId: id });
        }
      };
      try {
        setState({ status: WidgetStatus.Rendering, target });
        dispose.current = mountOfficialWidget(node.current, response, t("frameTitle"), operation.isCurrent, sdkFailure, () => {
          if (!operation.isCurrent() || failureReported) return;
          opening.current = false;
          setState({ status: WidgetStatus.Open, target });
        });
      } catch {
        response.credential = "";
        sdkFailure();
      }
    } catch (error) {
      if (operation.isLatest()) opening.current = false;
      if (operation.isCurrent()) setState({ status: WidgetStatus.Error, message: billingErrorKey(error), requestId: safeRequestId(error) || correlationId });
    }
  }, [begin, emailVerified, t]);

  const loading = state.status === WidgetStatus.Bootstrapping || state.status === WidgetStatus.Rendering;
  return { state, loading, attachNode, open, close };
}
