"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { ArrowLeft, Clock3, Mail, ShieldCheck } from "lucide-react";
import { findProduct, formatRubles, supportEmail } from "@/lib/catalog";

type StoredPaymentResult = {
  status?: string;
  productCode?: string;
  productName?: string;
  planName?: string;
  priceRub?: number;
  email?: string;
  autoRenew?: boolean;
  invoiceId?: string;
};

type PaymentStatusResponse = {
  email: string;
  product_state: {
    product_code: string;
    plan_code?: string | null;
    plan_name?: string | null;
    invoice_id?: string | null;
    transaction_id?: string | null;
    status: "inactive" | "pending" | "active" | "failed";
    starts_at?: string | null;
    expires_at?: string | null;
  };
};

const configuredApiBase =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const requestTimeoutMs = 5000;

function resolveApiBase(): string {
  if (typeof window === "undefined") {
    return configuredApiBase;
  }

  try {
    const url = new URL(configuredApiBase);
    const isLocalApiHost =
      url.hostname === "localhost" || url.hostname === "127.0.0.1";
    const isLocalBrowserHost =
      window.location.hostname === "localhost" ||
      window.location.hostname === "127.0.0.1";

    if (isLocalApiHost && !isLocalBrowserHost) {
      url.hostname = window.location.hostname;
    }

    return url.toString().replace(/\/$/, "");
  } catch {
    return configuredApiBase.replace(/\/$/, "");
  }
}

export function PaymentResultClient() {
  const searchParams = useSearchParams();
  const [stored, setStored] = useState<StoredPaymentResult>({});
  const [resolvedStatus, setResolvedStatus] = useState<string | null>(null);
  const [statusLoading, setStatusLoading] = useState(false);

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

  const status = searchParams.get("status") ?? stored.status ?? "pending";
  const email = searchParams.get("email") ?? stored.email ?? "не указан";
  const invoiceId = searchParams.get("invoice") ?? stored.invoiceId ?? "";
  const planName = product?.plan.name ?? stored.planName ?? "тариф не выбран";
  const price = product?.plan.priceRub ?? stored.priceRub;
  const effectiveStatus = resolvedStatus ?? status;
  const waiting = !["failed", "active"].includes(effectiveStatus);

  useEffect(() => {
    if (!invoiceId || !email || email === "не указан") {
      return;
    }

    let cancelled = false;
    async function pollStatus() {
      setStatusLoading(true);
      const controller = new AbortController();
      const timeoutId = window.setTimeout(
        () => controller.abort(),
        requestTimeoutMs
      );
      try {
        const response = await fetch(
          `${resolveApiBase()}/api/auth/payment-status?invoice_id=${encodeURIComponent(invoiceId)}&email=${encodeURIComponent(email)}`,
          {
            signal: controller.signal
          }
        );
        if (!response.ok) {
          return;
        }
        const payload = (await response.json()) as PaymentStatusResponse;
        if (cancelled) {
          return;
        }
        setResolvedStatus(payload.product_state.status);
      } finally {
        window.clearTimeout(timeoutId);
        if (!cancelled) {
          setStatusLoading(false);
        }
      }
    }

    void pollStatus();
    const intervalId = window.setInterval(() => {
      void pollStatus();
    }, 4000);

    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [email, invoiceId]);

  const isActive = effectiveStatus === "active";
  const finalTitle = isActive
    ? "Оплата подтверждена"
    : waiting
      ? "Платёж обрабатывается"
      : "Не удалось завершить оплату";

  return (
    <section className="page-section compact">
      <div className="result-panel">
        <span
          className={`badge ${
            isActive ? "badge-live" : waiting ? "badge-running" : "badge-demo"
          }`}
        >
          {isActive ? (
            <ShieldCheck size={12} aria-hidden="true" />
          ) : waiting ? (
            <Clock3 size={12} aria-hidden="true" />
          ) : (
            <ShieldCheck size={12} aria-hidden="true" />
          )}
          {isActive
            ? "Оплата подтверждена"
            : waiting
              ? "Ожидаем подтверждение"
              : "Платёж требует повторной попытки"}
        </span>
        <h1 className="result-title" style={{ marginTop: 18 }}>
          {finalTitle}
        </h1>
        <p className="hero-copy">
          {isActive
            ? "Платёж подтверждён платёжным партнёром. Доступ по выбранному тарифу обновлён."
            : waiting
            ? "Мы получили информацию о платеже и ждём подтверждение от платёжного партнёра. Статус подписки обновится после завершения обработки."
            : "Платёж не был подтверждён. Попробуйте повторить оплату позже или свяжитесь с поддержкой, если списание уже произошло."}
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
            <strong>Что дальше</strong>
            <p className="card-copy">
              {isActive
                ? "Можно вернуться к оформлению или дождаться следующего этапа интеграции, где активный доступ будет использоваться самими продуктами."
                : waiting
                ? "Если подтверждение пройдёт успешно, доступ к выбранному тарифу будет активирован автоматически. Обычно это занимает всего несколько минут."
                : "Проверьте способ оплаты и попробуйте ещё раз. Если деньги уже были списаны, напишите в поддержку и укажите email и детали операции."}
            </p>
          </div>
        </div>

        {invoiceId ? (
          <p className="muted" style={{ marginTop: 18, marginBottom: 0 }}>
            Invoice ID: {invoiceId}
            {statusLoading ? " · обновляем статус..." : ""}
          </p>
        ) : null}

        <div className="hero-actions">
          <Link className="btn-primary" href="/ru/auth-checkout">
            <ArrowLeft size={16} aria-hidden="true" />
            Вернуться к оформлению
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
