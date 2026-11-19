"use client";

import { useEffect, useEffectEvent, useState } from "react";
import type { PurchaseIntentResponse } from "@/generated/api-contracts/types.gen";
import { currentPurchase, purchaseStatus } from "@/shared/api/purchases";
import { ApiError } from "@/shared/api/transport";
import { subscribeToSessionChanges, useSessionOperation } from "@/shared/session/use-session-operation";
import { newRequestId } from "./errors";

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
  onStatus: (purchase: PurchaseIntentResponse) => void
) {
  const accept = useEffectEvent(onStatus);
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
    let delay = 2_000;
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
      try {
        const requestId = newRequestId();
        const purchase = purchaseId
          ? await purchaseStatus(token, purchaseId, requestId)
          : (await currentPurchase(token, uncertainProductId!, requestId)).purchase;
        if (stopped || !isCurrent()) { stop(); return; }
        if (purchase) {
          accept(purchase);
          if (!purchase.scope_held || !purchaseNeedsStatus(purchase)) stop();
        }
      } catch (error) {
        // A transient read failure leaves the last saved status and manual action intact.
        if (error instanceof ApiError && [401, 403, 404].includes(error.status)) stop();
      } finally {
        reading = false;
      }
      delay = delay === 2_000 ? 5_000 : 10_000;
      schedule();
    }

    return stop;
  }, [begin, key, purchaseId, recovering, uncertainProductId]);

  return { paused: key !== undefined && pausedKey === key, clearPause: () => setPausedKey(undefined) };
}
