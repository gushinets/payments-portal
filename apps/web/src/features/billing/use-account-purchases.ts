"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { AccountPurchaseResponse } from "@/generated/api-contracts/types.gen";
import { accountPurchases } from "@/shared/api/purchases";
import { subscribeToSessionChanges, useSessionOperation } from "@/shared/session/use-session-operation";
import { newRequestId } from "./errors";

export function useAccountPurchases(emailVerified: boolean) {
  const [items, setItems] = useState<AccountPurchaseResponse[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">(emailVerified ? "loading" : "ready");
  const busy = useRef(false);
  const { begin, cancel } = useSessionOperation();
  const fetchPage = useCallback((after?: string) => {
    if (busy.current || !emailVerified) return;
    busy.current = true;
    const operation = begin();
    async function request() {
      if (!operation.token) throw new Error("session_required");
      return accountPurchases(operation.token, newRequestId(), after);
    }
    void request().then((result) => {
      if (operation.isCurrent()) {
        setItems((previous) => after ? [...previous, ...result.purchases.filter((item) => !previous.some((old) => old.purchase_intent_id === item.purchase_intent_id))] : result.purchases);
        setCursor(result.next_cursor);
        setStatus("ready");
      }
    }, () => {
      if (operation.isCurrent()) setStatus("error");
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
      setStatus("error");
    });
    return () => { cancel(); busy.current = false; unsubscribe(); };
  }, [cancel, emailVerified, fetchPage]);

  function load(after?: string) {
    if (busy.current || !emailVerified) return;
    setStatus("loading");
    void fetchPage(after);
  }
  return { items, cursor, status, load };
}
