"use client";

import { useEffect, useEffectEvent, useState } from "react";
import type { PurchaseIntentResponse } from "@/generated/api-contracts/types.gen";
import { currentPurchase, purchaseStatus } from "@/shared/api/purchases";
import { subscribeToSessionChanges, useSessionOperation } from "@/shared/session/use-session-operation";
import { newRequestId, purchaseReadRefusal, type PurchaseReadRefusal } from "./errors";

const fastPollWindowMs = 120_000;
const recoveryPollIntervalMs = 60_000;
// The worker can discover the original operation for two hours. Allow a final status read after that window.
const recoveryPollWindowMs = 2 * 60 * 60_000 + 2 * recoveryPollIntervalMs;

export function purchaseNeedsStatus(purchase: Pick<PurchaseIntentResponse, "state">): boolean {
  return purchase.state === "created" || purchase.state === "preparing" || purchase.state === "awaiting_external_result";
}

export function usePurchaseStatusPoll(
  purchase: Pick<PurchaseIntentResponse, "purchase_intent_id" | "state"> | undefined,
  uncertainProductId: string | undefined,
  onStatus: (purchase: PurchaseIntentResponse, readStartedAt: number) => void,
  onRefused: (refusal: PurchaseReadRefusal) => void,
  initialDelayMs = 2_000
) {
  const accept = useEffectEvent(onStatus);
  const refuse = useEffectEvent(onRefused);
  const { begin } = useSessionOperation();
  const [pausedKey, setPausedKey] = useState<string>();
  const purchaseId = purchase?.purchase_intent_id;
  const key = purchaseId ?? uncertainProductId;
  const recovering = purchase?.state === "awaiting_external_result";

  useEffect(() => {
    if (!key) return;
    const { token, isCurrent } = begin();
    if (!token) return;

    const startedAt = Date.now();
    const fastUntil = startedAt + fastPollWindowMs;
    const stopAt = recovering ? startedAt + recoveryPollWindowMs : fastUntil;
    let delay = initialDelayMs;
    let timer: number | undefined;
    let reading = false;
    let stopped = false;
    const unsubscribe = subscribeToSessionChanges(stop);
    document.addEventListener("visibilitychange", schedule);
    schedule();

    function stop() {
      stopped = true;
      window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", schedule);
      unsubscribe();
    }

    function schedule() {
      window.clearTimeout(timer);
      if (stopped || reading || document.hidden) return;
      const now = Date.now();
      const nextDelay = now < fastUntil ? Math.min(delay, fastUntil - now) : recoveryPollIntervalMs;
      timer = window.setTimeout(() => void poll(), Math.max(0, Math.min(nextDelay, stopAt - now)));
    }

    async function poll() {
      if (stopped || !isCurrent() || !token) { stop(); return; }
      if (document.hidden) return;
      if (Date.now() >= stopAt) {
        stop();
        setPausedKey(key);
        return;
      }
      reading = true;
      const requestId = newRequestId();
      try {
        const readStartedAt = performance.now();
        const purchase = purchaseId
          ? await purchaseStatus(token, purchaseId, requestId)
          : (await currentPurchase(token, uncertainProductId!, requestId)).purchase;
        if (stopped || !isCurrent()) { stop(); return; }
        if (purchase) accept(purchase, readStartedAt);
      } catch (error) {
        const refusal = purchaseReadRefusal(error, requestId);
        if (refusal) {
          if (!stopped && isCurrent()) refuse(refusal);
          stop();
          return;
        }
      } finally {
        reading = false;
      }
      delay = delay < 2_000 ? 2_000 : delay < 5_000 ? 5_000 : 10_000;
      schedule();
    }

    return stop;
  }, [begin, initialDelayMs, key, purchaseId, recovering, uncertainProductId]);

  return { paused: key !== undefined && pausedKey === key, clearPause: () => setPausedKey(undefined) };
}
