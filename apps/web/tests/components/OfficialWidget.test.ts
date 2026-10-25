import { afterEach, describe, expect, it, vi } from "vitest";

import { mountOfficialWidget } from "@/features/purchases/official-widget-sdk";
import type { WidgetBootstrapResponse } from "@/generated/api-contracts/types.gen";

const response = (): WidgetBootstrapResponse => ({
  mode: "LOCAL_043", sdk: "lbxwidget", widget_origin: "https://043.lbxbilling.ru",
  serviceBaseUrl: "https://043.lbxbilling.ru/api/rest/v1/client", credential: "test-only.jwt.value",
  disableCreateSubscription: true, disableEditSubscription: true, disableStopSubscription: true,
  disableAutopayments: true, disablePayments: true, disableInvoiceGeneration: true
});

// A protocol test double, not a Widget runtime. No script or remote resource executes.
class Channel {
  static latest: Channel;
  port1 = { onmessage: null as ((event: { data: unknown }) => void) | null, postMessage: vi.fn(), close: vi.fn() };
  port2 = { close: vi.fn() };
  constructor() { Channel.latest = this; }
}

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); document.body.replaceChildren(); });

describe("official Widget isolated lifetime", () => {
  it("uses the exact allowlist, sandbox, all six flags and a memory-only channel", () => {
    vi.stubGlobal("MessageChannel", Channel);
    const node = document.createElement("div");
    document.body.append(node);
    const bootstrap = response();
    const fail = vi.fn();
    const dispose = mountOfficialWidget(node, bootstrap, "Billing", () => true, fail);
    const iframe = node.querySelector("iframe")!;
    expect(iframe.sandbox?.value ?? iframe.getAttribute("sandbox")).toBe("allow-scripts allow-same-origin");
    expect(iframe.referrerPolicy).toBe("no-referrer");
    const host = decodeURIComponent(iframe.src.split(",")[1]);
    expect(host).toContain("https://043.lbxbilling.ru/lbxwidget.js");
    expect(host).toContain("Content-Security-Policy");
    expect(host).not.toContain(bootstrap.credential);
    expect(iframe.src).not.toContain(bootstrap.credential);
    for (const flag of ["disableCreateSubscription", "disableEditSubscription", "disableStopSubscription", "disableAutopayments", "disablePayments", "disableInvoiceGeneration"]) {
      expect(host).toContain(`${flag}:true`);
    }
    Channel.latest.port1.onmessage?.({ data: "ready" });
    expect(Channel.latest.port1.postMessage).toHaveBeenCalledWith(bootstrap.credential);
    dispose();
    expect(node.children).toHaveLength(0);
    expect(Channel.latest.port1.close).toHaveBeenCalled();
    expect(fail).not.toHaveBeenCalled();
  });

  it("suppresses late script/session handoff, tears down on unmount and fails safely on timeout", () => {
    vi.useFakeTimers();
    vi.stubGlobal("MessageChannel", Channel);
    const node = document.createElement("div");
    let current = true;
    const fail = vi.fn();
    const dispose = mountOfficialWidget(node, response(), "Billing", () => current, fail);
    const channel = Channel.latest;
    current = false;
    channel.port1.onmessage?.({ data: "ready" });
    expect(channel.port1.postMessage).not.toHaveBeenCalled();
    expect(node.children).toHaveLength(0);
    dispose();
    current = true;
    mountOfficialWidget(node, response(), "Billing", () => current, fail);
    vi.advanceTimersByTime(20000);
    expect(fail).toHaveBeenCalledTimes(1);
    expect(node.children).toHaveLength(0);
  });

  it("refuses recorded credentials and mismatched service origins before creating a frame", () => {
    const node = document.createElement("div");
    expect(() => mountOfficialWidget(node, { ...response(), credential: "SIMULATED:stub" }, "Billing", () => true, vi.fn())).toThrow();
    expect(() => mountOfficialWidget(node, { ...response(), serviceBaseUrl: null }, "Billing", () => true, vi.fn())).toThrow();
    expect(node.children).toHaveLength(0);
  });
});
