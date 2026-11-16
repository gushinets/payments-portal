"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiErrorCode } from "@/shared/api/transport";
import { subscribeToSessionChanges, useSessionOperation } from "@/shared/session/use-session-operation";
import { newRequestId, safeRequestId } from "./errors";

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

export function usePaidRead<T>(enabled: boolean, read: (token: string, requestId: string) => Promise<T>, expiry: (data: T, started: number) => number | null = noExpiry) {
  const [state, setState] = useState<PaidReadState<T>>({ status: PaidReadStatus.Loading });
  const { begin, cancel } = useSessionOperation();
  const stopped = useRef(false);
  const busy = useRef(false);
  const boundToken = useRef<string | null | undefined>(undefined);
  const refresh = useCallback(async () => {
    if (!enabled || stopped.current || busy.current || !isVisible()) return;
    busy.current = true;
    setState({ status: PaidReadStatus.Loading });
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
      if (operation.isCurrent()) setState({ status: PaidReadStatus.Unavailable, requestId: safeRequestId(error) || requestId, deadlinePending: apiErrorCode(error) === "paid_access_deadline_pending" });
    } finally {
      if (operation.isLatest()) {
        busy.current = false;
        if (!operation.isCurrent()) {
          stopped.current = true;
          setState({ status: PaidReadStatus.Unavailable, requestId: "", deadlinePending: false });
        }
      }
    }
  }, [begin, cancel, enabled, expiry, read]);

  useEffect(() => {
    stopped.current = false;
    queueMicrotask(() => void refresh());
    const interval = setInterval(() => void refresh(), paidReadRefreshMs);
    const onVisibility = () => {
      if (isVisible()) void refresh();
      else setState({ status: PaidReadStatus.Loading });
    };
    const unsubscribe = subscribeToSessionChanges(() => {
      stopped.current = true;
      cancel();
      clearInterval(interval);
      busy.current = false;
      setState({ status: PaidReadStatus.Unavailable, requestId: "", deadlinePending: false });
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
    if (state.status !== PaidReadStatus.Ready || state.expiresAt === null) return;
    const timer = setTimeout(() => {
      setState({ status: PaidReadStatus.Unavailable, requestId: "", deadlinePending: true });
      void refresh();
    }, Math.max(0, state.expiresAt - performance.now()));
    return () => clearTimeout(timer);
  }, [refresh, state]);
  return { state, refresh };
}
