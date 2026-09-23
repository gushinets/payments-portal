import { ProductOverview } from "@/features/catalog";

export default function ProductsPage() {
  return (
    <>
      <section className="page-section compact">
        <div className="eyebrow">
          <span className="eyebrow-dot" />
          Каталог
        </div>
        <h1 className="legal-title">Продукты и тарифы</h1>
        <p className="hero-copy">
          Ознакомьтесь с сервисами AnytoolAI. Тарифы и оформление покупок
          временно недоступны.
        </p>
        <ProductOverview />
      </section>
    </>
  );
}
