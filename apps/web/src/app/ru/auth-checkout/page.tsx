import { Suspense } from "react";
import { CheckoutClient } from "@/features/checkout";

export default function AuthCheckoutPage() {
  return (
    <Suspense fallback={<CheckoutFallback />}>
      <CheckoutClient />
    </Suspense>
  );
}

function CheckoutFallback() {
  return (
    <section className="page-section compact">
      <div className="form-panel">Загрузка checkout-сценария...</div>
    </section>
  );
}
