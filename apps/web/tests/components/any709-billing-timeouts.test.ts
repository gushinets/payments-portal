import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getSession } from "@/shared/api/auth";
import { bootstrapWidget } from "@/shared/api/billing";
import { billingRequestTimeoutMs } from "@/shared/api/billing-policy";
import { advancePurchase, confirmPurchase, currentPurchase, purchaseStatus, reviewPurchase } from "@/shared/api/purchases";
import { requestTimeoutMs } from "@/shared/api/transport";
import { purchaseReview, savedPurchase, widgetResponse } from "../fixtures/purchase";

const fetcher = vi.fn<typeof fetch>();
const liveRequests: [string, () => Promise<unknown>, unknown][] = [
  ["review", () => reviewPurchase("synthetic-session", "proposal_ai", "synthetic-request"), purchaseReview],
  ["confirm", () => confirmPurchase("synthetic-session", {
    product_id: purchaseReview.product_id, revision_id: purchaseReview.revision_id,
    expected_fingerprint: purchaseReview.expected_fingerprint,
    documents: purchaseReview.documents.map(({ document_version_id, acceptance_text_hash }) => ({ document_version_id, acceptance_text_hash }))
  }, "original-key", "synthetic-request"), savedPurchase],
  ["advance", () => advancePurchase("synthetic-session", savedPurchase.purchase_intent_id, "synthetic-request"), savedPurchase],
  ["widget", () => bootstrapWidget("synthetic-session", "synthetic-request", savedPurchase.purchase_intent_id), widgetResponse(true)]
];

function delayedResponse(payload: unknown, delayMs: number) {
  fetcher.mockImplementation((_input, init) => new Promise<Response>((resolve, reject) => {
    const timer = window.setTimeout(() => resolve(Response.json(payload)), delayMs);
    init?.signal?.addEventListener("abort", () => {
      window.clearTimeout(timer);
      reject(new DOMException("synthetic_timeout", "AbortError"));
    }, { once: true });
  }));
}

function delayedBody(payload: unknown, status: number, delayMs: number) {
  fetcher.mockImplementation(async (_input, init) => {
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        const timer = window.setTimeout(() => {
          init?.signal?.removeEventListener("abort", abort);
          controller.enqueue(new TextEncoder().encode(JSON.stringify(payload)));
          controller.close();
        }, delayMs);
        function abort() {
          window.clearTimeout(timer);
          controller.error(new DOMException("synthetic_body_timeout", "AbortError"));
        }
        init?.signal?.addEventListener("abort", abort, { once: true });
      }
    });
    return new Response(stream, { status, headers: { "Content-Type": "application/json" } });
  });
}

beforeEach(() => { vi.useFakeTimers(); fetcher.mockReset(); vi.stubGlobal("fetch", fetcher); });
afterEach(() => { vi.clearAllTimers(); vi.useRealTimers(); vi.unstubAllGlobals(); });

describe("ANY-709 live billing request deadlines", () => {
  it.each(liveRequests)("%s waits for a successful response beyond the old five-second deadline", async (_name, request, payload) => {
    // The incident's successful server advance took 5.555 seconds.
    delayedResponse(payload, 5556);
    const result = request();
    await vi.advanceTimersByTimeAsync(requestTimeoutMs);
    expect(fetcher.mock.calls[0][1]?.signal?.aborted).toBe(false);
    await vi.advanceTimersByTimeAsync(556);
    await expect(result).resolves.toEqual(payload);
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it.each(liveRequests)("%s still aborts at a finite billing deadline without retrying", async (_name, request, payload) => {
    delayedResponse(payload, billingRequestTimeoutMs + 1);
    const result = expect(request()).rejects.toMatchObject({ name: "AbortError" });
    await vi.advanceTimersByTimeAsync(billingRequestTimeoutMs);
    await result;
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it.each(liveRequests)("%s keeps its deadline through a successful response body", async (_name, request, payload) => {
    delayedBody(payload, 200, billingRequestTimeoutMs + 1);
    const result = expect(request()).rejects.toMatchObject({ name: "AbortError" });
    await vi.advanceTimersByTimeAsync(billingRequestTimeoutMs);
    expect(fetcher.mock.calls[0][1]?.signal?.aborted).toBe(true);
    await result;
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it.each(liveRequests)("%s keeps its deadline through an error response body", async (_name, request) => {
    delayedBody({ detail: { code: "billing_busy", request_id: "synthetic-request" } }, 503, billingRequestTimeoutMs + 1);
    const result = expect(request()).rejects.toMatchObject({ name: "AbortError" });
    await vi.advanceTimersByTimeAsync(billingRequestTimeoutMs);
    expect(fetcher.mock.calls[0][1]?.signal?.aborted).toBe(true);
    await result;
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it.each([200, 503])("clears the deadline after the complete %s response body", async (status) => {
    const detail = { code: "billing_busy", request_id: "synthetic-request" };
    const payload = status === 200 ? savedPurchase : { detail };
    delayedBody(payload, status, 5556);
    const request = advancePurchase("synthetic-session", savedPurchase.purchase_intent_id, "synthetic-request");
    const result = status === 200
      ? expect(request).resolves.toEqual(payload)
      : expect(request).rejects.toMatchObject({ status: 503, detail });
    await vi.advanceTimersByTimeAsync(5556);
    await result;
    expect(fetcher.mock.calls[0][1]?.signal?.aborted).toBe(false);
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
    await vi.advanceTimersByTimeAsync(billingRequestTimeoutMs);
    expect(fetcher.mock.calls[0][1]?.signal?.aborted).toBe(false);
  });

  it.each([
    ["identity", () => getSession("synthetic-session")],
    ["current purchase", () => currentPurchase("synthetic-session", "proposal_ai", "synthetic-request")],
    ["saved status", () => purchaseStatus("synthetic-session", savedPurchase.purchase_intent_id, "synthetic-request")]
  ] as const)("%s retains the ordinary short timeout", async (_name, request) => {
    delayedResponse({}, requestTimeoutMs + 1);
    const result = expect(request()).rejects.toMatchObject({ name: "AbortError" });
    await vi.advanceTimersByTimeAsync(requestTimeoutMs);
    await result;
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
});
