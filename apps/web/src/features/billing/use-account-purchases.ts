"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { AccountPurchaseResponse, PurchaseIntentResponse } from "@/generated/api-contracts/types.gen";
import { accountPurchases } from "@/shared/api/purchases";
import { subscribeToSessionChanges, useSessionOperation } from "@/shared/session/use-session-operation";
import { newRequestId, reportBillingSessionRefusal, safeRequestId, type OnBillingSessionRefused } from "./errors";

type ReadState = { status: "loading" | "ready" } | { status: "error"; requestId: string };
type PurchaseSummary = Pick<AccountPurchaseResponse, "purchase_intent_id" | "product_id" | "state">;
type CabinetPurchase = PurchaseSummary & { checking?: true };
type ReadWindow = { startedAt: number; finishedAt: number };
type ObservedStatus = PurchaseSummary & Pick<PurchaseIntentResponse, "scope_held"> & { read: ReadWindow };
type Inventory = {
  entries: { purchase: PurchaseSummary; read: ReadWindow }[];
  completeRead?: ReadWindow;
};

function readFollows(next: ReadWindow, previous: ReadWindow): boolean {
  return next.startedAt > previous.finishedAt;
}

export function useAccountPurchases(enabled: boolean, onSessionRefused: OnBillingSessionRefused) {
  const [listed, setListed] = useState<Inventory>({ entries: [] });
  const [observed, setObserved] = useState(() => new Map<string, ObservedStatus>());
  const [cursor, setCursor] = useState<string | null>(null);
  const [state, setState] = useState<ReadState>({ status: enabled ? "loading" : "ready" });
  const busy = useRef(false);
  const { begin, cancel } = useSessionOperation();
  const fetchPage = useCallback((after?: string) => {
    if (busy.current || !enabled) return;
    busy.current = true;
    const operation = begin();
    const requestId = newRequestId();
    const readStartedAt = performance.now();
    setState({ status: "loading" });
    async function request() {
      if (!operation.token) throw new Error("session_required");
      return accountPurchases(operation.token, requestId, after);
    }
    void request().then((result) => {
      if (operation.isCurrent()) {
        const read = { startedAt: readStartedAt, finishedAt: performance.now() };
        setListed((previous) => {
          const page = result.purchases.map((purchase) => ({ purchase, read }));
          if (!after) return { entries: page, completeRead: result.next_cursor ? undefined : read };
          const existing = new Set(previous.entries.map(({ purchase }) => purchase.purchase_intent_id));
          return { entries: [...previous.entries, ...page.filter(({ purchase }) => !existing.has(purchase.purchase_intent_id))] };
        });
        setCursor(result.next_cursor);
        setState({ status: "ready" });
      }
    }, (error: unknown) => {
      if (!operation.isCurrent()) return;
      const id = safeRequestId(error) || requestId;
      setState({ status: "error", requestId: id });
      reportBillingSessionRefusal(error, id, onSessionRefused);
    }).finally(() => {
      if (operation.isLatest()) busy.current = false;
    });
  }, [begin, enabled, onSessionRefused]);

  useEffect(() => {
    if (enabled) void fetchPage();
    const unsubscribe = subscribeToSessionChanges(() => {
      cancel();
      busy.current = false;
      setListed({ entries: [] });
      setObserved(new Map());
      setCursor(null);
      setState({ status: "error", requestId: "" });
    });
    return () => { cancel(); busy.current = false; unsubscribe(); };
  }, [cancel, enabled, fetchPage]);

  function load(after?: string) {
    if (busy.current || !enabled) return;
    void fetchPage(after);
  }

  const applyStatus = useCallback(({ purchase_intent_id, product_id, state, scope_held }: PurchaseIntentResponse, readStartedAt: number) => {
    const read = { startedAt: readStartedAt, finishedAt: performance.now() };
    setObserved((previous) => {
      const current = previous.get(purchase_intent_id);
      // A released intent cannot regain its hold. Keep proof of release even across in-flight reads.
      if (current && (!current.scope_held || (scope_held && readFollows(current.read, read)))) return previous;
      return new Map(previous).set(purchase_intent_id, { purchase_intent_id, product_id, state, scope_held, read });
    });
  }, []);

  // Overlapping reads can sample the database in either order. The selected
  // purchase gets a fresh point read before either conflicting status is used.
  const items = listed.entries.flatMap<CabinetPurchase>(({ purchase, read }) => {
    const status = observed.get(purchase.purchase_intent_id);
    if (!status) return [purchase];
    if (!status.scope_held) return [];
    if (purchase.state === status.state || readFollows(read, status.read)) return [purchase];
    if (readFollows(status.read, read)) return [status];
    return [{ ...status, checking: true }];
  });

  function findPurchase(purchaseId: string): CabinetPurchase | undefined {
    const item = items.find((purchase) => purchase.purchase_intent_id === purchaseId);
    if (item) return item;
    const status = observed.get(purchaseId);
    if (!status?.scope_held) return;
    if (!listed.completeRead || readFollows(status.read, listed.completeRead)) return status;
    if (!readFollows(listed.completeRead, status.read)) return { ...status, checking: true };
  }

  return { items, cursor, status: state.status, requestId: state.status === "error" ? state.requestId : "", load, applyStatus, findPurchase };
}
