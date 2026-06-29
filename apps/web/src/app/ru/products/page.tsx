import { ProductCards } from "@/components/ProductCards";

export default function ProductsPage() {
  return (
    <section className="page-section compact">
      <div className="eyebrow">
        <span className="eyebrow-dot" />
        Catalog
      </div>
      <h1 className="legal-title">Продукты AnytoolAI</h1>
      <p className="hero-copy">
        Каталог первой версии намеренно короткий: два продукта, два стартовых
        тарифа, один RU legal/payment контур и demo-оплата до подключения
        CloudPayments.
      </p>
      <ProductCards />
    </section>
  );
}
