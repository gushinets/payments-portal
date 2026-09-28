import type { Metadata } from "next";

import { ProductOverview } from "@/features/catalog";
import { getCurrentRouteLocale } from "@/i18n/current-locale";
import { createLocalizedMetadata } from "@/i18n/metadata";

export async function generateMetadata(): Promise<Metadata> {
  return createLocalizedMetadata(await getCurrentRouteLocale(), "/products");
}

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
