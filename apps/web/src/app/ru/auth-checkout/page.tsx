"use client";

import { Suspense, useState } from "react";
import Script from "next/script";
import {
  CheckoutClient,
  type CheckoutAdapterStatus,
  registeredCheckoutAdapters
} from "@/features/checkout";

export default function AuthCheckoutPage() {
  const requiredAdapters = registeredCheckoutAdapters().filter((adapter) =>
    adapter.isRequired()
  );
  const [adapterStatus, setAdapterStatus] = useState<CheckoutAdapterStatus>(
    requiredAdapters.length > 0 ? "loading" : "disabled"
  );

  function markWidgetReady() {
    setAdapterStatus(
      requiredAdapters.every((adapter) => adapter.isReady()) ? "ready" : "failed"
    );
  }

  return (
    <>
      <Suspense fallback={<CheckoutFallback />}>
        <CheckoutClient checkoutAdapterStatus={adapterStatus} />
      </Suspense>
      {requiredAdapters.map((adapter) =>
        adapter.scriptSrc ? (
        <Script
          key={adapter.provider}
          src={adapter.scriptSrc}
          strategy="afterInteractive"
          onLoad={markWidgetReady}
          onReady={markWidgetReady}
          onError={() => setAdapterStatus("failed")}
        />
        ) : null
      )}
    </>
  );
}

function CheckoutFallback() {
  return (
    <section className="page-section compact">
      <div className="form-panel">Загрузка checkout-сценария...</div>
    </section>
  );
}
