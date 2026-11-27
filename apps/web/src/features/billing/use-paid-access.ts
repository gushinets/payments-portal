"use client";

import { useEffect } from "react";
import type { PaidAccessResponse } from "@/generated/api-contracts/types.gen";
import { readPaidAccess } from "@/shared/api/paid-access";
import type { OnBillingSessionRefused } from "./errors";
import { paidReadRefreshMs, usePaidRead } from "./use-paid-read";

export const paidAccessRefreshMs = paidReadRefreshMs;
const widgetFocusSampleMs = 250;
const expiry = (data: PaidAccessResponse, started: number) => data.effective_until
  ? started + Date.parse(data.effective_until) - Date.parse(data.read_at) : null;

export function usePaidAccess(
  enabled: boolean,
  onSessionRefused: OnBillingSessionRefused,
  paymentWidgetOpen: boolean,
) {
  const paid = usePaidRead(enabled, readPaidAccess, onSessionRefused, expiry);
  const { refresh } = paid;
  useEffect(() => {
    if (!enabled) return;
    let hadFocus = document.hasFocus();
    const onFocus = () => {
      hadFocus = true;
      void refresh({ afterCurrent: true, background: true });
    };
    window.addEventListener("focus", onFocus);
    // A payment popup can return focus to the cross-origin Widget frame
    // without dispatching focus in the cabinet's window.
    const sample = paymentWidgetOpen ? window.setInterval(() => {
      const focused = document.hasFocus();
      if (focused && !hadFocus) onFocus();
      hadFocus = focused;
    }, widgetFocusSampleMs) : undefined;
    return () => {
      window.removeEventListener("focus", onFocus);
      window.clearInterval(sample);
    };
  }, [enabled, paymentWidgetOpen, refresh]);
  return paid;
}
