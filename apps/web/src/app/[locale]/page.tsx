import type { Metadata } from "next";
import { ArrowRight } from "lucide-react";
import {
  ProductOverview,
  platformFacts,
  platformHighlights
} from "@/features/catalog";
import { getCurrentRouteLocale } from "@/i18n/current-locale";
import { createLocalizedMetadata } from "@/i18n/metadata";
import { Link } from "@/i18n/navigation";

export async function generateMetadata(): Promise<Metadata> {
  return createLocalizedMetadata(await getCurrentRouteLocale(), "/");
}

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
                можно узнать о продуктах и создать единый аккаунт.
              </p>
              <div className="hero-actions">
                <Link className="btn-primary" href="/auth-checkout">
                  Войти или зарегистрироваться
                  <ArrowRight size={16} aria-hidden="true" />
                </Link>
                <Link className="btn-secondary" href="#products">
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
        <h2 className="section-title">Сервисы для повседневной работы</h2>
        <p className="section-copy">
          Ознакомьтесь с продуктами AnytoolAI. Тарифы и оформление покупок
          временно недоступны.
        </p>
        <ProductOverview />
      </section>
    </>
  );
}
