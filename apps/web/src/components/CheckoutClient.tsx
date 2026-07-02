"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { ArrowRight, MailCheck, Send, ShieldCheck } from "lucide-react";
import { ProductCards } from "@/components/ProductCards";
import {
  demoPayment,
  findProduct,
  formatRubles,
  Product,
  products
} from "@/lib/catalog";

type LoginResponse = {
  status: string;
  email: string;
  demo_token?: string;
  demo_link?: string;
};

const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const cloudPaymentsEnabled =
  process.env.NEXT_PUBLIC_CLOUDPAYMENTS_ENABLED === "true";
const cloudPaymentsPublicId =
  process.env.NEXT_PUBLIC_CLOUDPAYMENTS_PUBLIC_ID ?? "";

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify(body)
  });

  if (!response.ok) {
    throw new Error(`API responded with ${response.status}`);
  }

  return response.json() as Promise<T>;
}

export function CheckoutClient() {
  const searchParams = useSearchParams();
  const initialProduct = searchParams.get("product");
  const [selectedCode, setSelectedCode] = useState(initialProduct ?? "");
  const selectedProduct = useMemo(
    () => findProduct(selectedCode),
    [selectedCode]
  );

  const [email, setEmail] = useState("");
  const [personalConsent, setPersonalConsent] = useState(false);
  const [linkSent, setLinkSent] = useState(false);
  const [verified, setVerified] = useState(false);
  const [offerConsent, setOfferConsent] = useState(false);
  const [autoRenew, setAutoRenew] = useState(false);
  const [recurrentConsent, setRecurrentConsent] = useState(false);
  const [demoToken, setDemoToken] = useState("");
  const [demoLink, setDemoLink] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const knownProductCodes = products.map((product) => product.code);
  const invalidProduct =
    initialProduct !== null && !knownProductCodes.includes(initialProduct as Product["code"]);

  async function requestMagicLink() {
    setError("");
    setNotice("");

    if (!selectedProduct) {
      setError("Выберите продукт для оформления.");
      return;
    }

    if (!email.includes("@")) {
      setError("Укажите корректный email.");
      return;
    }

    if (!personalConsent) {
      setError("Нужно дать согласие на обработку персональных данных.");
      return;
    }

    setLoading(true);
    try {
      const payload = await postJson<LoginResponse>("/api/auth/request-login", {
        email,
        product: selectedProduct.code,
        region: "ru"
      });
      setDemoToken(payload.demo_token ?? "demo-token");
      setDemoLink(payload.demo_link ?? "");
      setNotice(
        "Мы отправили magic link на email. Для первой версии доступен demo-режим подтверждения."
      );
    } catch {
      setDemoToken("demo-token");
      setDemoLink("");
      setNotice(
        "API недоступен или email-отправка не подключена. Используйте demo-подтверждение."
      );
    } finally {
      setLinkSent(true);
      setLoading(false);
    }
  }

  async function confirmEmail() {
    setError("");
    setLoading(true);
    try {
      await postJson("/api/auth/verify", {
        email,
        token: demoToken || "demo-token"
      });
    } catch {
      // Demo fallback is intentional for the first version.
    } finally {
      setVerified(true);
      setNotice("Email подтвержден в demo-режиме.");
      setLoading(false);
    }
  }

  function goToPaymentResult() {
    setError("");

    if (!selectedProduct) {
      setError("Выберите продукт для оплаты.");
      return;
    }

    if (!offerConsent) {
      setError("Перед оплатой нужно принять оферту и условия отмены.");
      return;
    }

    if (autoRenew && !recurrentConsent) {
      setError("Для автопродления нужно отдельное согласие на регулярные списания.");
      return;
    }

    const payload = {
      status: "demo",
      productCode: selectedProduct.code,
      productName: selectedProduct.name,
      planName: selectedProduct.plan.name,
      priceRub: selectedProduct.plan.priceRub,
      email,
      autoRenew
    };

    window.sessionStorage.setItem(
      "anytoolai_last_payment_result",
      JSON.stringify(payload)
    );

    if (cloudPaymentsEnabled && cloudPaymentsPublicId && window.cp?.CloudPayments) {
      const widget = new window.cp.CloudPayments({ language: "ru-RU" });
      widget.pay(
        "charge",
        {
          publicId: cloudPaymentsPublicId,
          description: selectedProduct.plan.paymentDescription,
          amount: selectedProduct.plan.priceRub,
          currency: "RUB",
          accountId: email,
          email
        },
        {
          onSuccess: () => {
            const params = new URLSearchParams({
              status: "pending",
              product: selectedProduct.code,
              plan: selectedProduct.plan.code,
              email
            });
            window.location.assign(`/ru/payment-result?${params.toString()}`);
          },
          onFail: () => {
            const params = new URLSearchParams({
              status: "demo",
              product: selectedProduct.code,
              plan: selectedProduct.plan.code,
              email
            });
            window.location.assign(`/ru/payment-result?${params.toString()}`);
          }
        }
      );
      return;
    }

    const params = new URLSearchParams({
      status: "demo",
      product: selectedProduct.code,
      plan: selectedProduct.plan.code,
      email
    });

    window.location.assign(`/ru/payment-result?${params.toString()}`);
  }

  return (
    <section className="page-section compact">
      <div className="eyebrow">
        <span className="eyebrow-dot" />
        Auth checkout
      </div>
      <h1 className="legal-title">Оформление подписки</h1>
      <p className="hero-copy">
        Product-aware entrypoint для первой RU-версии. Если `product` передан в
        URL, страница сразу показывает нужный продукт, тариф, пробный период и
        сценарий оформления. До подключения CloudPayments terminal id оплата
        работает как demo-заглушка и ведет на страницу результата.
      </p>

      {invalidProduct ? (
        <div className="notice error" style={{ marginTop: 24 }}>
          Неизвестный product code: {initialProduct}. Выберите один из продуктов
          ниже.
        </div>
      ) : null}

      <div className="two-column" style={{ marginTop: 28 }}>
        <div>
          {selectedProduct ? (
            <SelectedProductCard
              product={selectedProduct}
              onReset={() => setSelectedCode("")}
            />
          ) : (
            <div className="form-panel">
              <h2>Выберите продукт</h2>
              <p className="card-copy">
                Если параметр `product` не передан, checkout показывает выбор из
                двух продуктов первой версии.
              </p>
              <ProductCards />
            </div>
          )}
        </div>

        <div className="form-panel" id="checkout-form">
          <div className="form-grid">
            <span className="badge badge-running">
              <ShieldCheck size={12} aria-hidden="true" />
              Demo auth
            </span>
            <h2>1. Email и согласие</h2>
            <label className="field-label">
              Email
              <input
                className="input"
                type="email"
                autoComplete="email"
                placeholder="user@example.com"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                disabled={verified}
              />
            </label>

            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={personalConsent}
                disabled={verified}
                onChange={(event) => setPersonalConsent(event.target.checked)}
              />
              <span>
                Я даю согласие на обработку персональных данных в целях
                регистрации, идентификации пользователя, предоставления доступа к
                сервису и оформления подписки. Я ознакомлен с{" "}
                <Link className="inline-link" href="/ru/privacy">
                  Политикой обработки персональных данных
                </Link>
                .
              </span>
            </label>

            {!linkSent ? (
              <button
                className="btn-primary"
                type="button"
                onClick={requestMagicLink}
                disabled={loading}
              >
                <Send size={15} aria-hidden="true" />
                Получить ссылку для входа
              </button>
            ) : (
              <div className="notice">
                <MailCheck size={16} aria-hidden="true" /> Мы отправили magic
                link на email. Demo token:{" "}
                <span style={{ color: "var(--txt)" }}>{demoToken}</span>
                {demoLink ? (
                  <>
                    <br />
                    Demo link:{" "}
                    <span style={{ color: "var(--txt)" }}>{demoLink}</span>
                  </>
                ) : null}
              </div>
            )}

            {linkSent && !verified ? (
              <button
                className="btn-secondary"
                type="button"
                onClick={confirmEmail}
                disabled={loading}
              >
                Демо: подтвердить email
              </button>
            ) : null}

            {verified ? (
              <>
                <h2>2. Тариф и оплата</h2>
                <CheckoutSummary product={selectedProduct} />

                <div className="notice">
                  Планируемые способы оплаты: банковская карта, СБП, T-Pay и
                  Мир. До подключения terminal id страница работает в demo-режиме.
                </div>

                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={offerConsent}
                    onChange={(event) => setOfferConsent(event.target.checked)}
                  />
                  <span>
                    Я принимаю условия{" "}
                    <Link className="inline-link" href="/ru/offer">
                      оферты
                    </Link>{" "}
                    и{" "}
                    <Link className="inline-link" href="/ru/cancellation">
                      условия отмены подписки и возврата средств
                    </Link>
                    .
                  </span>
                </label>

                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={autoRenew}
                    onChange={(event) => {
                      setAutoRenew(event.target.checked);
                      if (!event.target.checked) {
                        setRecurrentConsent(false);
                      }
                    }}
                  />
                  <span>Включить автопродление</span>
                </label>

                {autoRenew ? (
                  <label className="checkbox-label">
                    <input
                      type="checkbox"
                      checked={recurrentConsent}
                      onChange={(event) =>
                        setRecurrentConsent(event.target.checked)
                      }
                    />
                    <span>
                      Я соглашаюсь на регулярное автоматическое списание средств
                      согласно выбранному тарифу. Подписка продлевается
                      автоматически до ее отмены. Условия описаны на странице{" "}
                      <Link className="inline-link" href="/ru/cancellation">
                        отмены и возврата
                      </Link>
                      .
                    </span>
                  </label>
                ) : null}

                <button
                  className="btn-primary"
                  type="button"
                  onClick={goToPaymentResult}
                  disabled={!selectedProduct}
                >
                  Оплатить
                  <ArrowRight size={16} aria-hidden="true" />
                </button>
              </>
            ) : null}

            <p className="muted" style={{ margin: 0 }}>
              Поддержка:{" "}
              <a className="inline-link" href="mailto:info@anytoolai.ru">
                info@anytoolai.ru
              </a>
            </p>
            {notice ? <div className="notice">{notice}</div> : null}
            {error ? <div className="notice error">{error}</div> : null}
          </div>
        </div>
      </div>
    </section>
  );
}

function SelectedProductCard({
  product,
  onReset
}: {
  product: Product;
  onReset: () => void;
}) {
  const Icon = product.Icon;

  function scrollToForm() {
    document
      .getElementById("checkout-form")
      ?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  return (
    <article className="tool-card active">
      <div className="tool-icon-wrap">
        <Icon size={22} aria-hidden="true" />
      </div>
      <span className="tool-tag">{product.type}</span>
      <h2>{product.name}</h2>
      <p className="muted" style={{ margin: "0 0 8px" }}>
        {product.tagline}
      </p>
      <p className="card-copy">{product.description}</p>
      <ul className="check-list">
        {product.valuePoints.map((point) => (
          <li key={point}>{point}</li>
        ))}
      </ul>
      <div className="price-line">
        <strong>{formatRubles(product.plan.priceRub)}</strong>
        <span>/ месяц</span>
      </div>
      <span className="badge badge-live">
        Пробный период {product.plan.trialDays} дней
      </span>
      <div className="button-row">
        <button className="btn-primary" type="button" onClick={scrollToForm}>
          Оформить
        </button>
        <button className="btn-secondary" type="button" onClick={onReset}>
          Посмотреть все продукты
        </button>
      </div>
    </article>
  );
}

function CheckoutSummary({ product }: { product?: Product }) {
  if (!product) {
    return (
      <div className="notice">
        Выберите продукт, чтобы увидеть тариф и перейти к demo-оплате.
      </div>
    );
  }

  return (
    <div className="notice">
      <strong style={{ color: "var(--txt)" }}>{product.plan.name}</strong>
      <br />
      {formatRubles(product.plan.priceRub)} / месяц · пробный период{" "}
      {product.plan.trialDays} дней
      <br />
      Тестовый платеж: {formatRubles(demoPayment.amountRub)} для проверки
      сценария. Подключение CloudPayments находится в процессе, а источником
      истины по оплате останется webhook.
      <br />
      Оплата будет доступна после подключения CloudPayments.
    </div>
  );
}
