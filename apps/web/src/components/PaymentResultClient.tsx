"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { ArrowLeft, Mail, ShieldCheck } from "lucide-react";
import { findProduct, formatRubles, supportEmail } from "@/lib/catalog";

type StoredPaymentResult = {
  status?: string;
  productCode?: string;
  productName?: string;
  planName?: string;
  priceRub?: number;
  email?: string;
  autoRenew?: boolean;
};

export function PaymentResultClient() {
  const searchParams = useSearchParams();
  const [stored, setStored] = useState<StoredPaymentResult>({});

  useEffect(() => {
    const id = window.setTimeout(() => {
      const raw = window.sessionStorage.getItem("anytoolai_last_payment_result");
      if (!raw) {
        return;
      }

      try {
        setStored(JSON.parse(raw) as StoredPaymentResult);
      } catch {
        setStored({});
      }
    }, 0);

    return () => window.clearTimeout(id);
  }, []);

  const product = useMemo(() => {
    const queryProduct = searchParams.get("product");
    return findProduct(queryProduct) ?? findProduct(stored.productCode);
  }, [searchParams, stored.productCode]);

  const status = searchParams.get("status") ?? stored.status ?? "demo";
  const email = searchParams.get("email") ?? stored.email ?? "не указан";
  const planName = product?.plan.name ?? stored.planName ?? "тариф не выбран";
  const price = product?.plan.priceRub ?? stored.priceRub;
  const title =
    status === "pending" ? "Платеж обрабатывается" : "Оплата пока не подключена";

  return (
    <section className="page-section compact">
      <div className="result-panel">
        <span className="badge badge-demo">
          <ShieldCheck size={12} aria-hidden="true" />
          {status}
        </span>
        <h1 className="result-title" style={{ marginTop: 18 }}>
          {title}
        </h1>
        <p className="hero-copy">
          Подключение CloudPayments находится в процессе. Эта страница нужна для
          UX возврата после платежа и для будущей интеграции, но сама не
          активирует подписку. Источник истины по оплате - webhook
          CloudPayments.
        </p>

        <div className="tools-grid" style={{ marginTop: 28 }}>
          <div className="feature-card">
            <strong>Продукт</strong>
            <p className="card-copy">{product?.name ?? "не выбран"}</p>
          </div>
          <div className="feature-card">
            <strong>Тариф</strong>
            <p className="card-copy">
              {planName}
              {price ? ` · ${formatRubles(price)} / месяц` : ""}
            </p>
          </div>
          <div className="feature-card">
            <strong>Email</strong>
            <p className="card-copy">{email}</p>
          </div>
          <div className="feature-card">
            <strong>Следующий шаг</strong>
            <p className="card-copy">
              После получения terminal id кнопка оплаты сможет открыть сценарий
              CloudPayments с суммой, валютой, описанием и email, но активация
              подписки по-прежнему должна происходить только по webhook.
            </p>
          </div>
        </div>

        <div className="hero-actions">
          <Link className="btn-primary" href="/ru/products">
            <ArrowLeft size={16} aria-hidden="true" />
            Вернуться к продуктам
          </Link>
          <a className="btn-secondary" href={`mailto:${supportEmail}`}>
            <Mail size={16} aria-hidden="true" />
            Поддержка
          </a>
        </div>
      </div>
    </section>
  );
}
