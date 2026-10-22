"use client";

import type { WidgetBootstrapResponse } from "@/generated/api-contracts/types.gen";

/** Our isolated SDK contract: no network, global credential, payment or access event.
 * dispose() belongs to this stub only; it makes no claim about LBX's teardown API.
 */
export function mountSimulatedWidget(
  node: HTMLElement,
  bootstrap: WidgetBootstrapResponse,
  label: string
): () => void {
  if (
    bootstrap.mode !== "SIMULATED" ||
    bootstrap.sdk !== "isolated_stub" ||
    bootstrap.widget_origin !== "self" ||
    !bootstrap.credential.startsWith("SIMULATED:") ||
    bootstrap.disableCreateSubscription !== true ||
    bootstrap.disableEditSubscription !== true
  ) {
    throw new Error("widget_configuration_refused");
  }
  // Check the ephemeral handoff, then discard it. Neither DOM nor a closure
  // retains the credential; the caller drops its response after this call.
  const content = document.createElement("p");
  content.setAttribute("role", "status");
  content.textContent = label;
  node.replaceChildren(content);
  return () => node.replaceChildren();
}
