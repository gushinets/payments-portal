"use client";

import { Suspense, useState } from "react";
import Script from "next/script";
import {
  CheckoutClient,
  type CloudPaymentsWidgetStatus
} from "@/features/checkout";

export default function AuthCheckoutPage() {
  const cloudPaymentsEnabled =
    process.env.NEXT_PUBLIC_CLOUDPAYMENTS_ENABLED === "true";
  const cloudPaymentsPublicId =
    process.env.NEXT_PUBLIC_CLOUDPAYMENTS_PUBLIC_ID;
  const widgetRequired = cloudPaymentsEnabled && !!cloudPaymentsPublicId;
  const [widgetStatus, setWidgetStatus] = useState<CloudPaymentsWidgetStatus>(
    widgetRequired ? "loading" : "disabled"
  );

  function markWidgetReady() {
    setWidgetStatus(window.cp?.CloudPayments ? "ready" : "failed");
  }

  return (
    <>
      <Suspense fallback={<CheckoutFallback />}>
        <CheckoutClient cloudPaymentsWidgetStatus={widgetStatus} />
      </Suspense>
      {widgetRequired ? (
        <Script
          src="https://widget.cloudpayments.ru/bundles/cloudpayments"
          strategy="afterInteractive"
          onLoad={markWidgetReady}
          onReady={markWidgetReady}
          onError={() => setWidgetStatus("failed")}
        />
      ) : null}
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
