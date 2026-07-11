import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { ProductCards } from "@/features/catalog";
import {
  formatRubles,
  platformFacts,
  platformHighlights
} from "@/features/catalog";

export default function RuHomePage() {
  return (
    <>
      <section className="page-section">
        <div className="bento-grid">
          <article className="hero-card">
            <div>
              <div className="eyebrow">
                <span className="eyebrow-dot" />
                AnytoolAI RU
              </div>
              <h1 className="hero-h1">
                Инструменты для работы с документами и{" "}
                <em className="h1-grad">улучшения промптов</em>
              </h1>
              <p className="hero-copy">
                AnytoolAI объединяет цифровые сервисы, которые помогают быстрее
                работать с контентом, документами и AI-инструментами. На сайте
                можно выбрать продукт, ознакомиться с тарифом и оформить
                подписку.
              </p>
              <div className="hero-actions">
                <Link className="btn-primary" href="#products">
                  Оформить подписку <ArrowRight size={16} aria-hidden="true" />
                </Link>
                <Link
                  className="btn-secondary"
                  href="#products"
                >
                  Выбрать продукт
                </Link>
              </div>
            </div>
            <aside className="hero-aside" aria-label="Ключевые параметры">
              <div className="stats-grid">
                {platformFacts.map((fact) => {
                  const Icon = fact.Icon;

                  return (
                    <div className="stat-cell" key={fact.label}>
                      <Icon className="stat-icon" aria-hidden="true" />
                      <div className="stat-val">{fact.value}</div>
                      <div className="stat-lbl">{fact.label}</div>
                      <div className="muted">{fact.detail}</div>
                    </div>
                  );
                })}
              </div>
            </aside>
          </article>

          {platformHighlights.map((item) => {
            const Icon = item.Icon;

            return (
              <article className="feature-card" key={item.title}>
                <Icon className="stat-icon" aria-hidden="true" />
                <strong>{item.title}</strong>
                <p className="card-copy">{item.description}</p>
              </article>
            );
          })}
        </div>
      </section>

      <section className="page-section compact" id="products">
        <div className="eyebrow">
          <span className="eyebrow-dot" />
          Продукты
        </div>
        <h2 className="section-title">Два сервиса для повседневной работы</h2>
        <p className="section-copy">
          Оба продукта доступны по подписке за {formatRubles(990)} в месяц с
          бесплатным периодом 7 дней.
        </p>
        <ProductCards />
      </section>
    </>
  );
}
