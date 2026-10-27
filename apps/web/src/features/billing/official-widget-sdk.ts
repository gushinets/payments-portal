"use client";

import type { WidgetBootstrapResponse } from "@/generated/api-contracts/types.gen";

// One SDK load per isolated browsing context. Remote code never shares the
// Portal origin/session storage. Removing the frame destroys its SDK memory;
// there is no invented vendor dispose method and no credential in HTML/URLs.
function hostDocument(origin: string, payment: boolean): string {
  return `<!doctype html><html><head>
<meta name="referrer" content="no-referrer">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline' ${origin}; connect-src ${origin}; frame-src ${origin}; style-src 'unsafe-inline' ${origin}; img-src data: ${origin}; font-src data: ${origin}; base-uri 'none'; form-action ${payment ? origin : "'none'"}">
<style>html,body,#widget{height:100%;margin:0}iframe{width:100%;height:100%;border:0}</style>
</head><body><div id="widget"></div><script>
"use strict";
let connected = false;
window.addEventListener("message", function connect(event) {
  if (connected || event.source !== parent || event.data !== "portal_widget_connect" || event.ports.length !== 1) return;
  connected = true;
  window.removeEventListener("message", connect);
  const port = event.ports[0];
  port.onmessage = function receive(event) {
    port.onmessage = null;
    let options = event.data;
    if (!options || typeof options.token !== "string" || !options.token) { port.postMessage("failed"); port.close(); return; }
    const script = document.createElement("script");
    script.src = "${origin}/lbxwidget.js";
    script.referrerPolicy = "no-referrer";
    script.onerror = function() { options = null; port.postMessage("failed"); port.close(); };
    script.onload = function() {
      try {
        if (typeof window.lbxwidget !== "function") throw new Error("widget_unavailable");
        window.lbxwidget(options).render("widget");
        port.postMessage("mounted");
      } catch { port.postMessage("failed"); }
      finally { options = null; port.close(); }
    };
    document.head.appendChild(script);
  };
  port.start();
  port.postMessage("ready");
});
</script></body></html>`;
}

const sdkTimeoutMs = 20000;

export function mountOfficialWidget(
  node: HTMLElement,
  bootstrap: WidgetBootstrapResponse,
  title: string,
  isCurrent: () => boolean,
  onFailure: () => void
): () => void {
  const origin = new URL(bootstrap.widget_origin);
  if (
    !["https:", "http:"].includes(origin.protocol) ||
    origin.origin !== bootstrap.widget_origin ||
    origin.username || origin.password || /[<>"'\s]/.test(bootstrap.widget_origin) ||
    bootstrap.sdk_url !== origin.origin + "/lbxwidget.js" ||
    bootstrap.serviceBaseUrl !== origin.origin + "/api/rest/v1/client" ||
    !bootstrap.credential ||
    !bootstrap.disableCreateSubscription || !bootstrap.disableEditSubscription ||
    !bootstrap.disableStopSubscription || !bootstrap.disableAutopayments ||
    !bootstrap.disableInvoiceGeneration ||
    (bootstrap.presentation === "account"
      ? !bootstrap.disablePayments || !!bootstrap.payment_target
      : bootstrap.presentation !== "payment" || bootstrap.disablePayments || !bootstrap.payment_target)
  ) throw new Error("widget_configuration_refused");

  let options: Record<string, string | boolean> | null = {
    token: bootstrap.credential,
    serviceBaseUrl: bootstrap.serviceBaseUrl,
    disableCreateSubscription: bootstrap.disableCreateSubscription,
    disableEditSubscription: bootstrap.disableEditSubscription,
    disableStopSubscription: bootstrap.disableStopSubscription,
    disableAutopayments: bootstrap.disableAutopayments,
    disablePayments: bootstrap.disablePayments,
    disableInvoiceGeneration: bootstrap.disableInvoiceGeneration
  };
  bootstrap.credential = "";
  const frame = document.createElement("iframe");
  frame.title = title;
  // The data URL has an opaque origin even with allow-same-origin, allowing
  // the nested HTTPS vendor frame to use its own Client API origin.
  // Payment methods may submit forms or open an acquiring window. Only the
  // proven payment presentation permits those user-driven browser actions.
  frame.setAttribute("sandbox", bootstrap.presentation === "payment"
    ? "allow-scripts allow-same-origin allow-forms allow-popups allow-popups-to-escape-sandbox allow-top-navigation-by-user-activation"
    : "allow-scripts allow-same-origin");
  frame.referrerPolicy = "no-referrer";
  frame.style.width = "100%";
  frame.style.height = "560px";
  frame.style.border = "0";
  const channel = new MessageChannel();
  let disposed = false;
  const dispose = () => {
    disposed = true;
    options = null;
    clearTimeout(timeout);
    channel.port1.close();
    channel.port2.close();
    frame.onload = null;
    frame.remove();
  };
  const timeout = setTimeout(() => {
    dispose();
    if (isCurrent()) onFailure();
  }, sdkTimeoutMs);
  channel.port1.onmessage = (event: MessageEvent<unknown>) => {
    if (disposed || !isCurrent()) { dispose(); return; }
    if (event.data === "ready") {
      channel.port1.postMessage(options);
      options = null;
    } else if (event.data === "mounted") {
      clearTimeout(timeout);
      channel.port1.close();
    } else {
      dispose();
      onFailure();
    }
  };
  frame.onload = () => {
    if (disposed || !isCurrent()) { dispose(); return; }
    // data: has an opaque origin, so '*' is required (Window.postMessage contract).
    // This exact Portal-created frame receives only the handshake/private port;
    // its parent-only listener connects before any remote SDK executes. The JWT
    // then travels on that port, never in a window message or the host URL.
    frame.contentWindow?.postMessage("portal_widget_connect", "*", [channel.port2]); // NOSONAR S2819: opaque data: receiver; handshake/port only. See docs/SECURITY.md.
    frame.onload = null;
  };
  frame.src = "data:text/html;charset=utf-8," + encodeURIComponent(hostDocument(origin.origin, bootstrap.presentation === "payment"));
  node.replaceChildren(frame);
  return dispose;
}
