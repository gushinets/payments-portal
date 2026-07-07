"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowRight, LogOut, UserRound } from "lucide-react";
import { formatRubles, products } from "@/lib/catalog";

type ProductState = {
  product_code: string;
  plan_code?: string | null;
  plan_name?: string | null;
  invoice_id?: string | null;
  transaction_id?: string | null;
  status: "inactive" | "pending" | "active" | "failed";
  starts_at?: string | null;
  expires_at?: string | null;
};

type SessionResponse = {
  authenticated: boolean;
  user: {
    tenant_id: string;
    region: string;
    user_id: string;
    email: string;
  };
  product_state?: ProductState | null;
};

const configuredApiBase =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const sessionStorageKey = "anytoolai_session_token_v1";
const sessionChangedEvent = "anytoolai_session_changed";
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

function statusLabel(status: ProductState["status"] | undefined): string {
  if (status === "active") {
    return "Подписка активна";
  }
  if (status === "pending") {
    return "Платёж ожидает подтверждения";
  }
  if (status === "failed") {
    return "Платёж не подтверждён";
  }
  return "Подписка не активна";
}

export function AccountClient() {
  const [email, setEmail] = useState("");
  const [states, setStates] = useState<Record<string, ProductState>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;

    async function loadAccount() {
      const token = window.localStorage.getItem(sessionStorageKey);
      if (!token) {
        setEmail("");
        setStates({});
        setLoading(false);
        setError("Войдите в аккаунт, чтобы увидеть статус подписок.");
        return;
      }

      setLoading(true);
      setError("");

      try {
        const payloads = await Promise.all(
          products.map(async (product) => {
            const controller = new AbortController();
            const timeoutId = window.setTimeout(
              () => controller.abort(),
              requestTimeoutMs
            );
            const response = await fetch(
              `${resolveApiBase()}/api/auth/session?product=${encodeURIComponent(product.code)}`,
              {
                headers: { Authorization: `Bearer ${token}` },
                signal: controller.signal
              }
            ).finally(() => window.clearTimeout(timeoutId));

            if (!response.ok) {
              throw new Error("session_error");
            }

            return response.json() as Promise<SessionResponse>;
          })
        );

        if (cancelled) {
          return;
        }

        setEmail(payloads[0]?.user.email ?? "");
        setStates(
          Object.fromEntries(
            payloads
              .map((payload) => payload.product_state)
              .filter((state): state is ProductState => Boolean(state))
              .map((state) => [state.product_code, state])
          )
        );
      } catch {
        window.localStorage.removeItem(sessionStorageKey);
        window.dispatchEvent(new Event(sessionChangedEvent));
        if (!cancelled) {
          setEmail("");
          setStates({});
          setError("Не удалось загрузить аккаунт. Войдите ещё раз.");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    const timerId = window.setTimeout(() => {
      void loadAccount();
    }, 0);
    window.addEventListener(sessionChangedEvent, loadAccount);

    return () => {
      cancelled = true;
      window.clearTimeout(timerId);
      window.removeEventListener(sessionChangedEvent, loadAccount);
    };
  }, []);

  function logout() {
    window.localStorage.removeItem(sessionStorageKey);
    window.dispatchEvent(new Event(sessionChangedEvent));
    window.location.assign("/ru");
  }

  if (loading) {
    return (
      <section className="page-section compact">
        <div className="form-panel">Загрузка аккаунта...</div>
      </section>
    );
  }

  if (error) {
    return (
      <section className="page-section compact">
        <div className="form-panel">
          <span className="badge badge-running">
            <UserRound size={12} aria-hidden="true" />
            Аккаунт
          </span>
          <h1 className="legal-title" style={{ marginTop: 14 }}>
            Личный кабинет
          </h1>
          <div className="notice" style={{ marginTop: 20 }}>
            {error}
          </div>
          <div className="hero-actions">
            <Link className="btn-primary" href="/ru">
              На главную
            </Link>
          </div>
        </div>
      </section>
    );
  }

  return (
    <section className="page-section compact">
      <div className="eyebrow">
        <span className="eyebrow-dot" />
        Аккаунт
      </div>
      <h1 className="legal-title">Личный кабинет</h1>
      <p className="hero-copy">
        Здесь отображается текущий аккаунт и статусы подписок по продуктам.
      </p>

      <div className="account-layout">
        <article className="form-panel account-summary-panel">
          <span className="badge badge-live">
            <UserRound size={12} aria-hidden="true" />
            Вход выполнен
          </span>
          <h2 style={{ marginTop: 14 }}>Аккаунт</h2>
          <p className="card-copy" style={{ marginBottom: 0 }}>
            {email}
          </p>
          <div className="hero-actions">
            <button className="btn-secondary" type="button" onClick={logout}>
              <LogOut size={15} aria-hidden="true" />
              Выйти
            </button>
          </div>
        </article>

        <div className="account-products-grid">
          {products.map((product) => {
            const state = states[product.code];
            const isActive = state?.status === "active";
            const isPending = state?.status === "pending";

            return (
              <article className="tool-card" key={product.code}>
                <span
                  className={`badge ${
                    isActive
                      ? "badge-live"
                      : isPending
                        ? "badge-running"
                        : "badge-demo"
                  }`}
                >
                  {statusLabel(state?.status)}
                </span>
                <h2 style={{ marginTop: 14 }}>{product.name}</h2>
                <p className="card-copy">{product.tagline}</p>
                <div className="tool-card-bottom">
                  <div className="price-line">
                    <strong>{formatRubles(product.plan.priceRub)}</strong>
                    <span>/ месяц</span>
                  </div>
                  {state?.expires_at ? (
                    <p className="muted" style={{ margin: "0 0 14px" }}>
                      Действует до{" "}
                      {new Date(state.expires_at).toLocaleDateString("ru-RU")}
                    </p>
                  ) : null}
                  <Link
                    className={isActive ? "btn-secondary" : "btn-primary"}
                    href={`/ru/auth-checkout?product=${product.code}`}
                  >
                    {isActive ? "Управлять" : "Оформить"}
                    <ArrowRight size={15} aria-hidden="true" />
                  </Link>
                </div>
              </article>
            );
          })}
        </div>
      </div>
    </section>
  );
}
