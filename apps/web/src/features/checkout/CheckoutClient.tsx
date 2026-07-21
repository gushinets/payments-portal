"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  ArrowRight,
  LogOut,
  MessageCircleMore,
  ShieldCheck
} from "lucide-react";
import { ProductCards } from "@/features/catalog";
import {
  findProduct,
  formatRubles,
  Product,
  products,
  supportEmail
} from "@/features/catalog";

type SessionUser = {
  tenant_id: string;
  region: string;
  user_id: string;
  email: string;
};

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
  user: SessionUser;
  product_state?: ProductState | null;
};

type AuthResponse = {
  status: string;
  token: string;
  user: SessionUser;
};

type CheckoutIntentResponse = {
  product_state: ProductState;
  checkout: {
    amount_minor: number;
    amount: number;
    currency: string;
  };
};

type RequiredDocument = {
  document_version_id: string;
  doc_type: string;
  version: string;
  title: string;
  url_path: string;
  acceptance_text: string;
  acceptance_text_hash: string;
};

type ApiErrorDetail =
  | string
  | {
      code?: string;
      documents?: RequiredDocument[];
    };

class ApiError extends Error {
  status: number;
  detail: ApiErrorDetail;

  constructor(status: number, detail: ApiErrorDetail, rawBody: string) {
    super(`${status}:${rawBody}`);
    this.status = status;
    this.detail = detail;
  }
}

const configuredApiBase =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const cloudPaymentsEnabled =
  process.env.NEXT_PUBLIC_CLOUDPAYMENTS_ENABLED === "true";
const cloudPaymentsPublicId =
  process.env.NEXT_PUBLIC_CLOUDPAYMENTS_PUBLIC_ID ?? "";
const telegramLoginUrl = process.env.NEXT_PUBLIC_TELEGRAM_LOGIN_URL ?? "";
const sessionStorageKey = "anytoolai_session_token_v1";
const sessionChangedEvent = "anytoolai_session_changed";
const requestTimeoutMs = 5000;

async function makeApiError(response: Response): Promise<ApiError> {
  const rawBody = await response.text();
  let detail: ApiErrorDetail = rawBody;

  try {
    const payload = JSON.parse(rawBody) as { detail?: ApiErrorDetail };
    detail = payload.detail ?? rawBody;
  } catch {
    detail = rawBody;
  }

  return new ApiError(response.status, detail, rawBody);
}

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

async function postJson<T>(
  path: string,
  body: unknown,
  token?: string
): Promise<T> {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), requestTimeoutMs);
  const response = await fetch(`${resolveApiBase()}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {})
    },
    body: JSON.stringify(body),
    signal: controller.signal
  }).finally(() => window.clearTimeout(timeoutId));

  if (!response.ok) {
    throw await makeApiError(response);
  }

  return response.json() as Promise<T>;
}

async function getJson<T>(path: string, token: string): Promise<T> {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), requestTimeoutMs);
  const response = await fetch(`${resolveApiBase()}${path}`, {
    headers: {
      Authorization: `Bearer ${token}`
    },
    signal: controller.signal
  }).finally(() => window.clearTimeout(timeoutId));

  if (!response.ok) {
    throw await makeApiError(response);
  }

  return response.json() as Promise<T>;
}

export function CheckoutClient() {
  const searchParams = useSearchParams();
  const initialProduct = searchParams.get("product");
  const initialAuthMode = searchParams.get("auth");
  const [selectedCode] = useState(initialProduct ?? "");
  const selectedProduct = useMemo(
    () => findProduct(selectedCode),
    [selectedCode]
  );
  const [mode, setMode] = useState<"login" | "register">(
    initialAuthMode === "login" ? "login" : "register"
  );
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [personalConsent, setPersonalConsent] = useState(false);
  const [offerConsent, setOfferConsent] = useState(false);
  const [autoRenew, setAutoRenew] = useState(false);
  const [recurrentConsent, setRecurrentConsent] = useState(false);
  const [sessionToken, setSessionToken] = useState("");
  const [sessionUser, setSessionUser] = useState<SessionUser | null>(null);
  const [productState, setProductState] = useState<ProductState | null>(null);
  const [missingDocuments, setMissingDocuments] = useState<RequiredDocument[]>([]);
  const [documentConsentById, setDocumentConsentById] = useState<
    Record<string, boolean>
  >({});
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [sessionLoading, setSessionLoading] = useState(false);
  const feedbackRef = useRef<HTMLDivElement | null>(null);

  const knownProductCodes = products.map((product) => product.code);
  const invalidProduct =
    initialProduct !== null &&
    !knownProductCodes.includes(initialProduct as Product["code"]);
  const needsAuthPrompt = !!selectedProduct && !sessionUser;
  const forceAuthPrompt = initialAuthMode === "login" && !sessionUser;
  const [authModalOpen, setAuthModalOpen] = useState(
    needsAuthPrompt || forceAuthPrompt
  );
  const showAuthModal =
    (needsAuthPrompt || forceAuthPrompt) && !sessionLoading && authModalOpen;
  const allMissingDocumentsAccepted =
    missingDocuments.length > 0 &&
    missingDocuments.every(
      (document) => documentConsentById[document.document_version_id]
    );

  useEffect(() => {
    function syncStoredToken() {
      const storedToken = window.localStorage.getItem(sessionStorageKey) ?? "";
      if (storedToken) {
        setSessionLoading(true);
        setSessionToken(storedToken);
      } else {
        setSessionToken("");
        setSessionUser(null);
        setProductState(null);
        setSessionLoading(false);
      }
    }

    const timerId = window.setTimeout(syncStoredToken, 0);
    window.addEventListener(sessionChangedEvent, syncStoredToken);

    return () => {
      window.clearTimeout(timerId);
      window.removeEventListener(sessionChangedEvent, syncStoredToken);
    };
  }, []);

  useEffect(() => {
    async function loadSession() {
      if (!sessionToken) {
        setSessionUser(null);
        setProductState(null);
        setSessionLoading(false);
        return;
      }

      setSessionLoading(true);

      try {
        const suffix = selectedCode
          ? `/api/auth/session?product=${encodeURIComponent(selectedCode)}`
          : "/api/auth/session";
        const payload = await getJson<SessionResponse>(suffix, sessionToken);
        setSessionUser(payload.user);
        setProductState(payload.product_state ?? null);
        setNotice("");
      } catch {
        window.localStorage.removeItem(sessionStorageKey);
        window.dispatchEvent(new Event(sessionChangedEvent));
        setSessionToken("");
        setSessionUser(null);
        setProductState(null);
        setNotice(
          "Не удалось проверить текущую сессию. Войдите снова через форму ниже."
        );
      } finally {
        setSessionLoading(false);
      }
    }

    void loadSession();
  }, [selectedCode, sessionToken]);

  useEffect(() => {
    if (!error && !notice) {
      return;
    }

    feedbackRef.current?.scrollIntoView({
      behavior: "smooth",
      block: "nearest"
    });
  }, [error, notice]);

  function showError(message: string) {
    setNotice("");
    setError(message);
  }

  function showNotice(message: string) {
    setError("");
    setNotice(message);
  }

  function getMissingDocuments(errorValue: unknown): RequiredDocument[] | null {
    if (!(errorValue instanceof ApiError) || errorValue.status !== 409) {
      return null;
    }

    if (
      typeof errorValue.detail === "object" &&
      errorValue.detail.code === "missing_required_documents" &&
      Array.isArray(errorValue.detail.documents)
    ) {
      return errorValue.detail.documents;
    }

    return null;
  }

  async function authenticate() {
    setError("");
    setNotice("");

    if (!email.includes("@")) {
      showError("Укажите корректный email.");
      return;
    }

    if (password.length < 8) {
      showError("Пароль должен содержать не менее 8 символов.");
      return;
    }

    if (mode === "register") {
      if (!personalConsent) {
        showError(
          "Для регистрации нужно отдельное согласие на обработку персональных данных."
        );
        return;
      }

      if (!offerConsent) {
        showError("Для регистрации нужно принять условия оферты.");
        return;
      }
    }

    setLoading(true);
    try {
      const payload =
        mode === "register"
          ? await postJson<AuthResponse>("/api/auth/register", {
              email,
              password,
              personal_consent: personalConsent,
              offer_consent: offerConsent
            })
          : await postJson<AuthResponse>("/api/auth/login", {
              email,
              password
            });

      window.localStorage.setItem(sessionStorageKey, payload.token);
      window.dispatchEvent(new Event(sessionChangedEvent));
      setSessionToken(payload.token);
      setSessionUser(payload.user);
      setMissingDocuments([]);
      setDocumentConsentById({});
      showNotice(
        mode === "register"
          ? "Аккаунт создан. Теперь можно перейти к оплате."
          : "Вход выполнен. Можно продолжить оформление."
      );
      setPassword("");
    } catch (requestError) {
      const message =
        requestError instanceof Error ? requestError.message : "auth_error";
      if (message.includes("409")) {
        showError("Аккаунт с таким email уже существует. Попробуйте войти.");
      } else if (message.includes("401")) {
        showError("Неверный email или пароль.");
      } else if (message.includes("missing_personal_consent")) {
        showError("Нужно дать согласие на обработку персональных данных.");
      } else if (message.includes("missing_offer_consent")) {
        showError("Нужно принять условия оферты.");
      } else {
        showError("Не удалось выполнить авторизацию. Попробуйте ещё раз.");
      }
    } finally {
      setLoading(false);
    }
  }

  async function logout() {
    setError("");
    setNotice("");

    if (!sessionToken) {
      return;
    }

    try {
      await postJson("/api/auth/logout", {}, sessionToken);
    } catch {
      // Session cleanup is safe even if backend logout fails.
    } finally {
      window.localStorage.removeItem(sessionStorageKey);
      window.dispatchEvent(new Event(sessionChangedEvent));
      setSessionToken("");
      setSessionUser(null);
      setProductState(null);
      setMissingDocuments([]);
      setDocumentConsentById({});
    }
  }

  async function goToPaymentResult() {
    setError("");

    if (!selectedProduct) {
      showError("Выберите продукт для оплаты.");
      return;
    }

    if (!sessionUser || !sessionToken) {
      showError("Сначала войдите или зарегистрируйтесь.");
      return;
    }

    if (autoRenew && !recurrentConsent) {
      showError(
        "Для автопродления нужно отдельное согласие на регулярные списания."
      );
      return;
    }

    let checkoutIntent: CheckoutIntentResponse;
    try {
      const payload = await postJson<CheckoutIntentResponse>(
        "/api/auth/checkout-intent",
        {
          product: selectedProduct.code,
          plan_code: selectedProduct.plan.code,
          auto_renew: autoRenew
        },
        sessionToken
      );
      checkoutIntent = payload;
      setProductState(payload.product_state);
      setMissingDocuments([]);
      setDocumentConsentById({});
    } catch (requestError) {
      const documents = getMissingDocuments(requestError);
      if (documents) {
        setMissingDocuments(documents);
        setDocumentConsentById({});
        showError("Перед оплатой нужно принять актуальные юридические документы.");
        return;
      }

      showError("Не удалось подготовить оплату. Попробуйте ещё раз.");
      return;
    }

    const resultPayload = {
      status: "pending",
      productCode: selectedProduct.code,
      productName: selectedProduct.name,
      planName: selectedProduct.plan.name,
      amount: checkoutIntent.checkout.amount,
      currency: checkoutIntent.checkout.currency,
      email: sessionUser.email,
      autoRenew,
      invoiceId: checkoutIntent.product_state.invoice_id ?? ""
    };

    window.sessionStorage.setItem(
      "anytoolai_last_payment_result",
      JSON.stringify(resultPayload)
    );

    if (cloudPaymentsEnabled && cloudPaymentsPublicId && window.cp?.CloudPayments) {
      const widget = new window.cp.CloudPayments({ language: "ru-RU" });
      widget.pay(
        "charge",
        {
          publicId: cloudPaymentsPublicId,
          description: selectedProduct.plan.paymentDescription,
          amount: checkoutIntent.checkout.amount,
          currency: checkoutIntent.checkout.currency,
          invoiceId: checkoutIntent.product_state.invoice_id ?? undefined,
          accountId: sessionUser.email,
          email: sessionUser.email,
          data: {
            product_code: selectedProduct.code,
            plan_code: selectedProduct.plan.code
          }
        },
        {
          onSuccess: () => {
            const params = new URLSearchParams({
              status: "pending",
              product: selectedProduct.code,
              plan: selectedProduct.plan.code,
              email: sessionUser.email,
              invoice: checkoutIntent.product_state.invoice_id ?? ""
            });
            window.location.assign(`/ru/payment-result?${params.toString()}`);
          },
          onFail: () => {
            const params = new URLSearchParams({
              status: "failed",
              product: selectedProduct.code,
              plan: selectedProduct.plan.code,
              email: sessionUser.email,
              invoice: checkoutIntent.product_state.invoice_id ?? ""
            });
            window.location.assign(`/ru/payment-result?${params.toString()}`);
          }
        }
      );
      return;
    }

    const params = new URLSearchParams({
      status: "pending",
      product: selectedProduct.code,
      plan: selectedProduct.plan.code,
      email: sessionUser.email,
      invoice: checkoutIntent.product_state.invoice_id ?? ""
    });
    window.location.assign(`/ru/payment-result?${params.toString()}`);
  }

  async function acceptRequiredDocumentsAndContinue() {
    setError("");

    if (!sessionToken) {
      showError("Сначала войдите или зарегистрируйтесь.");
      return;
    }

    if (!allMissingDocumentsAccepted) {
      showError("Отметьте каждый документ, который нужно принять перед оплатой.");
      return;
    }

    setLoading(true);
    try {
      for (const document of missingDocuments) {
        await postJson(
          "/api/legal/acceptances",
          {
            document_version_id: document.document_version_id,
            acceptance_text_hash: document.acceptance_text_hash,
            entrypoint_type: "product",
            entrypoint_value: selectedProduct?.code ?? null,
            source_url: window.location.pathname + window.location.search
          },
          sessionToken
        );
      }

      setMissingDocuments([]);
      setDocumentConsentById({});
      showNotice("Документы приняты. Продолжаем оформление оплаты.");
      await goToPaymentResult();
    } catch (requestError) {
      if (
        requestError instanceof ApiError &&
        requestError.detail === "invalid_acceptance_text_hash"
      ) {
        showError("Текст согласия изменился. Обновите страницу и попробуйте ещё раз.");
      } else {
        showError("Не удалось зафиксировать согласие. Попробуйте ещё раз.");
      }
    } finally {
      setLoading(false);
    }
  }

  const authForm = (
    <div className="form-grid">
      <span className="badge badge-running">
        <ShieldCheck size={12} aria-hidden="true" />
        Единый аккаунт
      </span>
      <h2>1. Вход или регистрация</h2>
      {needsAuthPrompt && !sessionLoading ? (
        <div className="notice">
          Чтобы продолжить оформление, войдите в аккаунт или зарегистрируйтесь.
        </div>
      ) : null}
      <div ref={feedbackRef}>
        {notice ? <div className="notice">{notice}</div> : null}
        {error ? <div className="notice error">{error}</div> : null}
      </div>
      <div className="auth-mode-row">
        <button
          className={mode === "register" ? "btn-primary" : "btn-secondary"}
          type="button"
          onClick={() => setMode("register")}
        >
          Регистрация
        </button>
        <button
          className={mode === "login" ? "btn-primary" : "btn-secondary"}
          type="button"
          onClick={() => setMode("login")}
        >
          Вход
        </button>
      </div>

      <label className="field-label">
        Email
        <input
          className="input"
          type="email"
          autoComplete="email"
          placeholder="user@example.com"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
      </label>

      <label className="field-label">
        Пароль
        <input
          className="input"
          type="password"
          autoComplete={mode === "register" ? "new-password" : "current-password"}
          placeholder="Не менее 8 символов"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
      </label>

      {mode === "register" ? (
        <>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={personalConsent}
              onChange={(event) => setPersonalConsent(event.target.checked)}
            />
            <span>
              Я даю согласие на обработку персональных данных в соответствии с{" "}
              <Link className="inline-link" href="/ru/consent-personal-data">
                Согласием на обработку персональных данных
              </Link>
              {" "}и{" "}
              <Link className="inline-link" href="/ru/privacy">
                Политикой в отношении обработки персональных данных
              </Link>
              .
            </span>
          </label>

          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={offerConsent}
              onChange={(event) => setOfferConsent(event.target.checked)}
            />
            <span>
              Я принимаю условия{" "}
              <Link className="inline-link" href="/ru/offer">
                Публичной оферты
              </Link>{" "}
              и ознакомлен(а) с{" "}
              <Link className="inline-link" href="/ru/cancellation">
                Условиями отмены подписки и возврата денежных средств
              </Link>
              .
            </span>
          </label>
        </>
      ) : null}

      <button
        className="btn-primary"
        type="button"
        onClick={authenticate}
        disabled={loading}
      >
        {mode === "register" ? "Создать аккаунт" : "Войти"}
        <ArrowRight size={15} aria-hidden="true" />
      </button>

      {telegramLoginUrl ? (
        <a className="btn-secondary telegram-button" href={telegramLoginUrl}>
          <MessageCircleMore size={16} aria-hidden="true" />
          Войти через Telegram
        </a>
      ) : null}
    </div>
  );

  return (
    <section className="page-section compact">
      <div className="eyebrow">
        <span className="eyebrow-dot" />
        Оформление подписки
      </div>
      <h1 className="legal-title">Оформление доступа к сервису</h1>
      <p className="hero-copy">
        Выберите продукт, войдите в аккаунт или зарегистрируйтесь и перейдите к
        оплате.
      </p>

      {invalidProduct ? (
        <div className="notice error" style={{ marginTop: 24 }}>
          Мы не нашли запрошенный продукт. Выберите один из доступных вариантов
          ниже.
        </div>
      ) : null}

      {showAuthModal ? (
        <>
          <button
            className="auth-modal-overlay"
            type="button"
            aria-label="Закрыть окно входа"
            onClick={() => setAuthModalOpen(false)}
          />
          <div
            className="form-panel auth-modal-panel"
            role="dialog"
            aria-modal="true"
            aria-label="Вход или регистрация"
          >
            {authForm}
          </div>
        </>
      ) : null}

      <div className="two-column checkout-grid" style={{ marginTop: 28 }}>
        <div>
          {selectedProduct ? (
            <SelectedProductCard product={selectedProduct} />
          ) : (
            <div className="form-panel checkout-equal-panel">
              <h2>Выберите продукт</h2>
              <p className="card-copy">
                Откройте нужный сервис, чтобы увидеть тариф, бесплатный лимит и
                перейти к оформлению.
              </p>
              <ProductCards />
            </div>
          )}
        </div>

        <div className="form-panel checkout-equal-panel" id="checkout-form">
          <div className="form-grid checkout-form-grid">
            <span className="badge badge-running">
              <ShieldCheck size={12} aria-hidden="true" />
              Единый аккаунт
            </span>

            {needsAuthPrompt && !sessionLoading ? (
              <div className="notice">
                Чтобы продолжить оформление, войдите в аккаунт или
                зарегистрируйтесь.
              </div>
            ) : null}

            {sessionLoading ? (
              <div className="notice">Проверяем текущую сессию...</div>
            ) : sessionUser ? (
              <>
                <h2 className="checkout-step-title">1. Аккаунт</h2>
                <div className="feedback-slot" ref={feedbackRef}>
                  {notice ? <div className="notice">{notice}</div> : null}
                  {error ? <div className="notice error">{error}</div> : null}
                </div>
                <div className="account-card checkout-account-card">
                  <div>
                    <strong>{sessionUser.email}</strong>
                    <p className="card-copy">
                      Вы вошли в единый аккаунт платформы.
                    </p>
                  </div>
                  <button className="btn-secondary" type="button" onClick={logout}>
                    <LogOut size={15} aria-hidden="true" />
                    Выйти
                  </button>
                </div>

                <h2 className="checkout-step-title">2. Статус подписки</h2>
                <SubscriptionState product={selectedProduct} state={productState} />

                {missingDocuments.length > 0 ? (
                  <div className="notice legal-consent-box">
                    <strong style={{ color: "var(--txt)" }}>
                      Нужно принять актуальные документы
                    </strong>
                    <div className="legal-consent-list">
                      {missingDocuments.map((document) => (
                        <div
                          className="legal-consent-item"
                          key={document.document_version_id}
                        >
                          <input
                            aria-label={`Принять документ ${document.title}`}
                            type="checkbox"
                            checked={
                              documentConsentById[
                                document.document_version_id
                              ] ?? false
                            }
                            onChange={(event) =>
                              setDocumentConsentById((current) => ({
                                ...current,
                                [document.document_version_id]:
                                  event.target.checked
                              }))
                            }
                          />
                          <div>
                            <Link className="inline-link" href={document.url_path}>
                              {document.title}
                            </Link>
                            <p>{document.acceptance_text}</p>
                          </div>
                        </div>
                      ))}
                    </div>
                    <button
                      className="btn-primary"
                      type="button"
                      onClick={acceptRequiredDocumentsAndContinue}
                      disabled={loading || !allMissingDocumentsAccepted}
                    >
                      Принять и продолжить
                      <ArrowRight size={16} aria-hidden="true" />
                    </button>
                  </div>
                ) : null}

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
                      автоматически до её отмены.
                    </span>
                  </label>
                ) : null}

                <button
                  className="btn-primary"
                  type="button"
                  onClick={goToPaymentResult}
                  disabled={!selectedProduct || missingDocuments.length > 0}
                >
                  Оплатить
                  <ArrowRight size={16} aria-hidden="true" />
                </button>
              </>
            ) : (
              <>
                <h2 className="checkout-step-title">1. Вход или регистрация</h2>
                <div className="feedback-slot" ref={feedbackRef}>
                  {notice ? <div className="notice">{notice}</div> : null}
                  {error ? <div className="notice error">{error}</div> : null}
                </div>
                <div className="notice">
                  Чтобы продолжить оформление, откройте окно входа или
                  регистрации.
                </div>
                <button
                  className="btn-primary"
                  type="button"
                  onClick={() => setAuthModalOpen(true)}
                >
                  Войти или зарегистрироваться
                  <ArrowRight size={15} aria-hidden="true" />
                </button>
              </>
            )}

            <p className="muted" style={{ margin: 0 }}>
              Поддержка:{" "}
              <a className="inline-link" href={`mailto:${supportEmail}`}>
                {supportEmail}
              </a>
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}

function SelectedProductCard({
  product
}: {
  product: Product;
}) {
  const Icon = product.Icon;

  function scrollToForm() {
    document
      .getElementById("checkout-form")
      ?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  return (
    <article className="tool-card checkout-equal-panel active">
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
      <div className="button-row" style={{ marginTop: 0 }}>
        <span className="badge badge-live">
          Пробный период {product.plan.trialDays} дней
        </span>
        <span className="badge badge-running">{product.freeLimit}</span>
      </div>
      <div className="button-row">
        <button className="btn-primary" type="button" onClick={scrollToForm}>
          Оформить
        </button>
      </div>
    </article>
  );
}

function SubscriptionState({
  product,
  state
}: {
  product?: Product;
  state: ProductState | null;
}) {
  if (!product) {
    return (
      <div className="notice">
        Выберите продукт, чтобы увидеть статус подписки и перейти к оплате.
      </div>
    );
  }

  const status = state?.status ?? "inactive";
  const statusText =
    status === "active"
      ? "Подписка активна"
      : status === "pending"
        ? "Платёж ожидает подтверждения"
        : "Подписка не активна";

  return (
    <div className="notice">
      <strong style={{ color: "var(--txt)" }}>{product.plan.name}</strong>
      <br />
      Статус: {statusText}
      <br />
      Стоимость: {formatRubles(product.plan.priceRub)} / месяц
      <br />
      Бесплатный лимит: {product.freeLimit}
      {state?.expires_at ? (
        <>
          <br />
          Действует до: {new Date(state.expires_at).toLocaleDateString("ru-RU")}
        </>
      ) : null}
    </div>
  );
}
