import { ProductCards } from "@/components/ProductCards";
import {
  demoPayment,
  formatRubles,
  paymentMethods
} from "@/lib/catalog";

export default function ProductsPage() {
  return (
    <>
      <section className="page-section compact">
        <div className="eyebrow">
          <span className="eyebrow-dot" />
          RU products
        </div>
        <h1 className="legal-title">Продукты и тарифы первой версии</h1>
        <p className="hero-copy">
          В RU MVP показываем два цифровых продукта, два демонстрационных
          месячных тарифа и checkout-сценарий, подготовленный под CloudPayments.
        </p>
        <ProductCards />
      </section>

      <section className="page-section compact">
        <div className="two-column">
          <article className="form-panel">
            <span className="badge badge-demo">Demo payment</span>
            <h2 style={{ marginTop: 14 }}>{demoPayment.name}</h2>
            <p className="card-copy">
              Для проверки будущего платежного сценария в интерфейсе показан
              тестовый вариант на {formatRubles(demoPayment.amountRub)}.
            </p>
            <p className="card-copy">
              Назначение: {demoPayment.purpose}. В первой версии до получения
              CloudPayments terminal id реальный платеж не выполняется.
            </p>
          </article>

          <article className="form-panel">
            <span className="badge badge-running">Payment methods</span>
            <h2 style={{ marginTop: 14 }}>Планируемые способы оплаты</h2>
            <p className="card-copy">
              На сайте показаны только те способы оплаты, которые планируется
              подключать через CloudPayments. После подключения состав можно
              скорректировать под фактически активированные методы.
            </p>
            <div className="payment-list" aria-label="Планируемые способы оплаты">
              {paymentMethods.map((method) => (
                <span className="payment-pill" key={method}>
                  {method}
                </span>
              ))}
            </div>
          </article>
        </div>
      </section>
    </>
  );
}
