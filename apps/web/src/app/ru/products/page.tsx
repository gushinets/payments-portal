import { ProductCards } from "@/components/ProductCards";

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
          Выберите сервис, сравните возможности и перейдите к оформлению
          подписки.
        </p>
        <ProductCards />
      </section>
    </>
  );
}
