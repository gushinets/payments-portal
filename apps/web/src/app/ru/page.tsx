import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { ProductCards } from "@/components/ProductCards";
import {
  formatRubles,
  platformFacts,
  platformHighlights,
  products,
  supportEmail
} from "@/lib/catalog";

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
                <Link className="btn-primary" href="/ru/auth-checkout">
                  Оформить подписку <ArrowRight size={16} aria-hidden="true" />
                </Link>
                <Link
                  className="btn-secondary"
                  href="/ru/auth-checkout?product=document-summary"
                >
                  Открыть Document Summary
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

      <section className="page-section compact">
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

      <section className="page-section compact">
        <div className="two-column">
          {products.map((product) => (
            <article className="form-panel" key={product.code}>
              <span className="badge badge-running">{product.plan.name}</span>
              <h2 style={{ marginTop: 14 }}>{product.name}</h2>
              <p className="card-copy">{product.tagline}</p>
              <p className="card-copy">
                {formatRubles(product.plan.priceRub)} / месяц · {product.freeLimit}
              </p>
              <div className="hero-actions" style={{ marginTop: 20 }}>
                <Link
                  className="btn-primary"
                  href={`/ru/auth-checkout?product=${product.code}`}
                >
                  Оформить
                </Link>
                <Link
                  className="btn-secondary"
                  href={`/ru/auth-checkout?product=${product.code}`}
                >
                  Подробнее
                </Link>
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className="page-section compact">
        <div className="two-column">
          <article className="form-panel">
            <span className="badge badge-running">Юридическая информация</span>
            <h2 style={{ marginTop: 14 }}>Документы опубликованы на сайте</h2>
            <p className="card-copy">
              На сайте доступны политика обработки персональных данных, оферта,
              условия отмены и возврата, политика cookie и политика
              информационной безопасности.
            </p>
          </article>
          <article className="form-panel">
            <span className="badge badge-live">Поддержка</span>
            <h2 style={{ marginTop: 14 }}>Связь по вопросам подписки</h2>
            <p className="card-copy">
              Если у вас возникли вопросы по оплате, доступу или документам,
              напишите на{" "}
              <a className="inline-link" href={`mailto:${supportEmail}`}>
                {supportEmail}
              </a>
              .
            </p>
          </article>
        </div>
      </section>
    </>
  );
}
