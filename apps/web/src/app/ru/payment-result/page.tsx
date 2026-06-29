import { Suspense } from "react";
import { PaymentResultClient } from "@/components/PaymentResultClient";

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
