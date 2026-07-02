import Link from "next/link";
import { ArrowRight, ShieldCheck } from "lucide-react";
import { ProductCards } from "@/components/ProductCards";
import {
  demoPayment,
  formatRubles,
  platformFacts,
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
                RU MVP · CloudPayments ready
              </div>
              <h1 className="hero-h1">
                AnytoolAI для оформления работ,{" "}
                <em className="h1-grad">контроля scope и подписок</em>
              </h1>
              <p className="hero-copy">
                Платформа цифровых сервисов для оформления работ, контроля
                изменений scope и подписочного доступа к инструментам. В первой
                RU-версии показываем два продукта, тарифы, checkout, legal
                pages и подготовленный контур CloudPayments в demo-режиме.
              </p>
              <div className="hero-actions">
                <Link className="btn-primary" href="/ru/auth-checkout">
                  Оформить <ArrowRight size={16} aria-hidden="true" />
                </Link>
                <Link
                  className="btn-secondary"
                  href="/ru/auth-checkout?product=jobact"
                >
                  Попробовать
                </Link>
              </div>
            </div>
            <aside className="hero-aside" aria-label="Ключевые параметры MVP">
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

          <article className="feature-card">
            <strong>Product-aware checkout</strong>
            <p className="card-copy">
              `/ru/auth-checkout?product=...` сразу показывает нужный продукт и
              тариф без лишнего каталога.
            </p>
          </article>
          <article className="feature-card">
            <strong>Demo magic link</strong>
            <p className="card-copy">
              Email flow работает в демонстрационном режиме без реальной отправки
              писем.
            </p>
          </article>
          <article className="feature-card">
            <strong>Webhook first</strong>
            <p className="card-copy">
              Страница результата не активирует подписку. Источник истины для
              оплаты - webhook.
            </p>
          </article>
        </div>
      </section>

      <section className="page-section compact">
        <div className="eyebrow">
          <span className="eyebrow-dot" />
          Products
        </div>
        <h2 className="section-title">Два продукта первой версии</h2>
        <p className="section-copy">
          Тарифы указаны в рублях, пробный период составляет 7 дней. Реальная
          оплата будет доступна после подключения CloudPayments terminal id.
        </p>
        <ProductCards />
      </section>

      <section className="page-section compact">
        <div className="two-column">
          {products.map((product) => (
            <article className="form-panel" key={product.code}>
              <span className="badge badge-running">{product.plan.name}</span>
              <h2 style={{ marginTop: 14 }}>{product.name}</h2>
              <p className="card-copy">
                {formatRubles(product.plan.priceRub)} / месяц · бесплатный
                пробный период {product.plan.trialDays} дней.
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
                  Попробовать
                </Link>
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className="page-section compact">
        <div className="two-column">
          <article className="form-panel">
            <span className="badge badge-demo">Demo payment</span>
            <h2 style={{ marginTop: 14 }}>{demoPayment.name}</h2>
            <p className="card-copy">
              В интерфейсе показан {formatRubles(demoPayment.amountRub)} для
              проверки платежного сценария. До подключения терминала кнопка
              оплаты ведет на страницу результата оплаты.
            </p>
          </article>
          <article className="form-panel">
            <span className="badge badge-running">
              <ShieldCheck size={12} aria-hidden="true" />
              Legal contour
            </span>
            <h2 style={{ marginTop: 14 }}>Документы доступны без авторизации</h2>
            <p className="card-copy">
              Политика ПДн, оферта, условия отмены, cookies и безопасность
              опубликованы как RU draft. Финальная версия должна пройти проверку
              юриста перед запуском реальных платежей.
            </p>
            <p className="card-copy">
              Поддержка:{" "}
              <a className="inline-link" href={`mailto:${supportEmail}`}>
                {supportEmail}
              </a>
            </p>
          </article>
        </div>
      </section>
    </>
  );
}
