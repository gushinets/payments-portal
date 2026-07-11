import { Suspense } from "react";
import { PaymentResultClient } from "@/features/payment-result";

export default function PaymentResultPage() {
  return (
    <Suspense fallback={<PaymentResultFallback />}>
      <PaymentResultClient />
    </Suspense>
  );
}

function PaymentResultFallback() {
  return (
    <section className="page-section compact">
      <div className="result-panel">Загрузка результата оплаты...</div>
    </section>
  );
}
