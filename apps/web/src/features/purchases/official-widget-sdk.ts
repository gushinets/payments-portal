"use client";

import type { WidgetBootstrapResponse } from "@/generated/api-contracts/types.gen";

// The opaque sandbox owns the vendor global and all SDK memory. Destroying the
// entire context tears it down without inventing a vendor dispose() method or
// letting remote code read the Portal session. No JWT is put in HTML or a URL.
const hostDocument = `<!doctype html><html><head>
<meta name="referrer" content="no-referrer">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline' 'unsafe-eval' https://043.lbxbilling.ru; connect-src https://043.lbxbilling.ru; frame-src https://043.lbxbilling.ru; style-src 'unsafe-inline' https://043.lbxbilling.ru; img-src data: https://043.lbxbilling.ru; font-src data: https://043.lbxbilling.ru; base-uri 'none'; form-action 'none'">
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
    let token = typeof event.data === "string" ? event.data : "";
    if (!token || token.startsWith("SIMULATED:")) { port.postMessage("failed"); port.close(); return; }
    const script = document.createElement("script");
    script.src = "https://043.lbxbilling.ru/lbxwidget.js";
    script.referrerPolicy = "no-referrer";
    script.onerror = function() { token = ""; port.postMessage("failed"); port.close(); };
    script.onload = function() {
      try {
        if (typeof window.lbxwidget !== "function") throw new Error("widget_unavailable");
        window.lbxwidget({token, serviceBaseUrl:"https://043.lbxbilling.ru/api/rest/v1/client",
          disableCreateSubscription:true, disableEditSubscription:true,
          disableStopSubscription:true, disableAutopayments:true,
          disablePayments:true, disableInvoiceGeneration:true}).render("widget");
        port.postMessage("mounted");
      } catch { port.postMessage("failed"); }
      finally { token = ""; port.close(); }
    };
    document.head.appendChild(script);
  };
  port.start();
  port.postMessage("ready");
});
</script></body></html>`;

export function mountOfficialWidget(
  node: HTMLElement,
  bootstrap: WidgetBootstrapResponse,
  title: string,
  isCurrent: () => boolean,
  onFailure: () => void
): () => void {
  if (
    bootstrap.mode !== "LOCAL_043" ||
    bootstrap.sdk !== "lbxwidget" ||
    bootstrap.widget_origin !== "https://043.lbxbilling.ru" ||
    bootstrap.serviceBaseUrl !== "https://043.lbxbilling.ru/api/rest/v1/client" ||
    bootstrap.credential.startsWith("SIMULATED:") ||
    !bootstrap.credential ||
    !bootstrap.disableCreateSubscription ||
    !bootstrap.disableEditSubscription ||
    !bootstrap.disableStopSubscription ||
    !bootstrap.disableAutopayments ||
    !bootstrap.disablePayments ||
    !bootstrap.disableInvoiceGeneration
  ) throw new Error("widget_configuration_refused");

  let token = bootstrap.credential;
  const frame = document.createElement("iframe");
  frame.title = title;
  // data: gives this host an opaque origin, even with allow-same-origin.
  // The nested HTTPS vendor frame retains its OWN origin for Client API reads;
  // neither context shares the Portal origin or its session storage.
  frame.setAttribute("sandbox", "allow-scripts allow-same-origin");
  frame.referrerPolicy = "no-referrer";
  frame.style.width = "100%";
  frame.style.height = "560px";
  frame.style.border = "0";
  const channel = new MessageChannel();
  let disposed = false;
  const dispose = () => {
    disposed = true;
    token = "";
    clearTimeout(timeout);
    channel.port1.close();
    channel.port2.close();
    frame.remove();
  };
  const timeout = setTimeout(() => {
    dispose();
    if (isCurrent()) onFailure();
  }, 20000);
  channel.port1.onmessage = (event: MessageEvent<unknown>) => {
    if (disposed || !isCurrent()) { dispose(); return; }
    if (event.data === "ready") {
      channel.port1.postMessage(token);
      token = "";
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
    frame.contentWindow?.postMessage("portal_widget_connect", "*", [channel.port2]);
    frame.onload = null;
  };
  frame.src = "data:text/html;charset=utf-8," + encodeURIComponent(hostDocument);
  node.replaceChildren(frame);
  return dispose;
}
