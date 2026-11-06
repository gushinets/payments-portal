"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { PaidAccessResponse } from "@/generated/api-contracts/types.gen";
import { readPaidAccess } from "@/shared/api/paid-access";
import { apiErrorCode } from "@/shared/api/transport";
import { subscribeToSessionChanges, useSessionOperation } from "@/shared/session/use-session-operation";
import { newRequestId, safeRequestId } from "./errors";

export const paidAccessRefreshMs = 30_000;
const isVisible = () => document.visibilityState !== "hidden";
type PaidReadState =
  | { status: "loading" }
  | { status: "ready"; data: PaidAccessResponse; expiresAt: number | null }
  | { status: "unavailable"; requestId: string; deadlinePending: boolean };

export function usePaidAccess(enabled: boolean) {
  const [state, setState] = useState<PaidReadState>({ status: "loading" });
  const { begin, cancel } = useSessionOperation();
  const stopped = useRef(false);
  const busy = useRef(false);
  const boundToken = useRef<string | null | undefined>(undefined);
  const refresh = useCallback(async () => {
    if (!enabled || stopped.current || busy.current || !isVisible()) return;
    busy.current = true;
    setState({ status: "loading" });
    const operation = begin();
    if (boundToken.current === undefined) boundToken.current = operation.token;
    if (boundToken.current !== operation.token) {
      stopped.current = true;
      cancel();
      busy.current = false;
      setState({ status: "unavailable", requestId: "", deadlinePending: false });
      return;
    }
    const requestId = newRequestId();
    const started = performance.now();
    try {
      if (!operation.token) throw new Error("session_required");
      const data = await readPaidAccess(operation.token, requestId);
      if (!operation.isCurrent()) return;
      // Server duration measured from request start expires conservatively;
      // the browser never extends a paid deadline using its wall clock.
      const expiresAt = data.effective_until ? started + Date.parse(data.effective_until) - Date.parse(data.read_at) : null;
      if (!isVisible()) setState({ status: "loading" });
      else setState(expiresAt === null || expiresAt > performance.now()
        ? { status: "ready", data, expiresAt }
        : { status: "unavailable", requestId, deadlinePending: true });
    } catch (error) {
      if (operation.isCurrent()) setState({ status: "unavailable", requestId: safeRequestId(error) || requestId, deadlinePending: apiErrorCode(error) === "paid_access_deadline_pending" });
    } finally {
      if (operation.isLatest()) {
        busy.current = false;
        if (!operation.isCurrent()) {
          stopped.current = true;
          setState({ status: "unavailable", requestId: "", deadlinePending: false });
        }
      }
    }
  }, [begin, cancel, enabled]);

  useEffect(() => {
    stopped.current = false;
    queueMicrotask(() => void refresh());
    const interval = setInterval(() => void refresh(), paidAccessRefreshMs);
    const onVisibility = () => {
      if (isVisible()) void refresh();
      else setState({ status: "loading" });
    };
    const unsubscribe = subscribeToSessionChanges(() => {
      stopped.current = true;
      cancel();
      clearInterval(interval);
      busy.current = false;
      setState({ status: "unavailable", requestId: "", deadlinePending: false });
    });
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      stopped.current = true;
      cancel();
      clearInterval(interval);
      busy.current = false;
      unsubscribe();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [cancel, refresh]);

  useEffect(() => {
    if (state.status !== "ready" || state.expiresAt === null) return;
    const timer = setTimeout(() => {
      setState({ status: "unavailable", requestId: "", deadlinePending: true });
      void refresh();
    }, Math.max(0, state.expiresAt - performance.now()));
    return () => clearTimeout(timer);
  }, [refresh, state]);
  return { state, refresh };
}
