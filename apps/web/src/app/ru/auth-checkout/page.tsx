import { Suspense } from "react";
import Script from "next/script";
import { CheckoutClient } from "@/features/checkout";

export default function AuthCheckoutPage() {
  const cloudPaymentsEnabled =
    process.env.NEXT_PUBLIC_CLOUDPAYMENTS_ENABLED === "true";
  const cloudPaymentsPublicId =
    process.env.NEXT_PUBLIC_CLOUDPAYMENTS_PUBLIC_ID;

  return (
    <>
      <Suspense fallback={<CheckoutFallback />}>
        <CheckoutClient />
      </Suspense>
      {cloudPaymentsEnabled && cloudPaymentsPublicId ? (
        <Script
          src="https://widget.cloudpayments.ru/bundles/cloudpayments"
          strategy="afterInteractive"
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
