"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { AccountPurchaseResponse } from "@/generated/api-contracts/types.gen";
import { accountPurchases } from "@/shared/api/purchases";
import { subscribeToSessionChanges, useSessionOperation } from "@/shared/session/use-session-operation";
import { newRequestId, safeRequestId } from "./errors";

type ReadState = { status: "loading" | "ready" } | { status: "error"; requestId: string };

export function useAccountPurchases(emailVerified: boolean) {
  const [items, setItems] = useState<AccountPurchaseResponse[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [state, setState] = useState<ReadState>({ status: emailVerified ? "loading" : "ready" });
  const busy = useRef(false);
  const { begin, cancel } = useSessionOperation();
  const fetchPage = useCallback((after?: string) => {
    if (busy.current || !emailVerified) return;
    busy.current = true;
    const operation = begin();
    const requestId = newRequestId();
    setState({ status: "loading" });
    async function request() {
      if (!operation.token) throw new Error("session_required");
      return accountPurchases(operation.token, requestId, after);
    }
    void request().then((result) => {
      if (operation.isCurrent()) {
        setItems((previous) => after ? [...previous, ...result.purchases.filter((item) => !previous.some((old) => old.purchase_intent_id === item.purchase_intent_id))] : result.purchases);
        setCursor(result.next_cursor);
        setState({ status: "ready" });
      }
    }, (error: unknown) => {
      if (operation.isCurrent()) setState({ status: "error", requestId: safeRequestId(error) || requestId });
    }).finally(() => {
      if (operation.isLatest()) busy.current = false;
    });
  }, [begin, emailVerified]);

  useEffect(() => {
    if (emailVerified) void fetchPage();
    const unsubscribe = subscribeToSessionChanges(() => {
      cancel();
      busy.current = false;
      setItems([]);
      setCursor(null);
      setState({ status: "error", requestId: "" });
    });
    return () => { cancel(); busy.current = false; unsubscribe(); };
  }, [cancel, emailVerified, fetchPage]);

  function load(after?: string) {
    if (busy.current || !emailVerified) return;
    void fetchPage(after);
  }
  return { items, cursor, status: state.status, requestId: state.status === "error" ? state.requestId : "", load };
}
