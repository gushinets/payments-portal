"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, apiErrorCode } from "@/shared/api/transport";
import { subscribeToSessionChanges, useSessionOperation } from "@/shared/session/use-session-operation";
import { billingSessionRefusal, newRequestId, safeRequestId, type OnBillingSessionRefused } from "./errors";

export const paidReadRefreshMs = 30_000;
const noExpiry = () => null;
const isVisible = () => document.visibilityState !== "hidden";
export enum PaidReadStatus {
  Loading = "loading",
  Ready = "ready",
  Unavailable = "unavailable",
}

type PaidReadState<T> =
  | { status: PaidReadStatus.Loading }
  | { status: PaidReadStatus.Ready; data: T; expiresAt: number | null }
  | { status: PaidReadStatus.Unavailable; requestId: string; deadlinePending: boolean };

type PaidReadRefreshOptions = { afterCurrent?: boolean; background?: boolean };

export function usePaidRead<T>(
  enabled: boolean,
  read: (token: string, requestId: string) => Promise<T>,
  onSessionRefused: OnBillingSessionRefused,
  expiry: (data: T, started: number) => number | null = noExpiry,
) {
  const [state, setState] = useState<PaidReadState<T>>({ status: PaidReadStatus.Loading });
  const { begin, cancel } = useSessionOperation();
  const stopped = useRef(false);
  const busy = useRef(false);
  const refreshPending = useRef<PaidReadRefreshOptions | null>(null);
  const boundToken = useRef<string | null | undefined>(undefined);
  const refresh = useCallback(async function refreshPaidRead(options: PaidReadRefreshOptions = {}): Promise<void> {
    if (!enabled || stopped.current || !isVisible()) return;
    if (busy.current) {
      if (options.afterCurrent && !refreshPending.current?.background) refreshPending.current = options;
      return;
    }
    busy.current = true;
    const operation = begin();
    if (boundToken.current === undefined) boundToken.current = operation.token;
    if (boundToken.current !== operation.token) {
      stopped.current = true;
      cancel();
      busy.current = false;
      setState({ status: PaidReadStatus.Unavailable, requestId: "", deadlinePending: false });
      return;
    }
    const requestId = newRequestId();
    const started = performance.now();
    setState((current) => options.background && current.status === PaidReadStatus.Ready
      && (current.expiresAt === null || current.expiresAt > started)
      ? current : { status: PaidReadStatus.Loading });
    try {
      if (!operation.token) throw new Error("session_required");
      const data = await read(operation.token, requestId);
      if (!operation.isCurrent()) return;
      // Server duration measured from request start expires conservatively;
      // the browser never extends a paid deadline using its wall clock.
      const expiresAt = expiry(data, started);
      if (!isVisible()) setState({ status: PaidReadStatus.Loading });
      else setState(expiresAt === null || expiresAt > performance.now()
        ? { status: PaidReadStatus.Ready, data, expiresAt }
        : { status: PaidReadStatus.Unavailable, requestId, deadlinePending: true });
    } catch (error) {
      if (!operation.isCurrent()) return;
      const id = safeRequestId(error) || requestId;
      const code = apiErrorCode(error);
      const busyBackground = options.background && error instanceof ApiError && error.status === 503 && code === "paid_access_busy";
      const receivedAt = performance.now();
      setState((current) => {
        if (busyBackground && current.status === PaidReadStatus.Ready
          && current.expiresAt !== null && current.expiresAt > receivedAt) {
          return current;
        }
        return { status: PaidReadStatus.Unavailable, requestId: id, deadlinePending: code === "paid_access_deadline_pending" };
      });
      const refusal = billingSessionRefusal(error, id);
      if (refusal) {
        stopped.current = true;
        onSessionRefused(refusal);
      }
    } finally {
      if (operation.isLatest()) {
        busy.current = false;
        const pending = refreshPending.current;
        refreshPending.current = null;
        if (!operation.isCurrent()) {
          stopped.current = true;
          setState({ status: PaidReadStatus.Unavailable, requestId: "", deadlinePending: false });
        } else if (pending) {
          void refreshPaidRead(pending);
        }
      }
    }
  }, [begin, cancel, enabled, expiry, onSessionRefused, read]);

  useEffect(() => {
    if (!enabled) return;
    stopped.current = false;
    queueMicrotask(() => void refresh());
    const interval = setInterval(() => void refresh(), paidReadRefreshMs);
    const onVisibility = () => {
      if (isVisible()) void refresh({ afterCurrent: true });
      else {
        refreshPending.current = null;
        setState({ status: PaidReadStatus.Loading });
      }
    };
    const unsubscribe = subscribeToSessionChanges(() => {
      stopped.current = true;
      cancel();
      clearInterval(interval);
      busy.current = false;
      refreshPending.current = null;
      setState({ status: PaidReadStatus.Unavailable, requestId: "", deadlinePending: false });
    });
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      stopped.current = true;
      cancel();
      clearInterval(interval);
      busy.current = false;
      refreshPending.current = null;
      unsubscribe();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [cancel, enabled, refresh]);

  useEffect(() => {
    if (state.status !== PaidReadStatus.Ready || state.expiresAt === null) return;
    const timer = setTimeout(() => {
      setState({ status: PaidReadStatus.Unavailable, requestId: "", deadlinePending: true });
      void refresh();
    }, Math.max(0, state.expiresAt - performance.now()));
    return () => clearTimeout(timer);
  }, [refresh, state]);
  return { state, refresh };
}
