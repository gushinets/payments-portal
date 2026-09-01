"use client";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  ArrowRight,
  LogOut,
  MessageCircleMore,
  ShieldCheck,
  Sparkles
} from "lucide-react";
import {
  getCatalogProducts,
  ProductCards,
  type CatalogProduct
} from "@/features/catalog";
import {
  ApiError,
  authErrorMessage,
  decodeAuthSessionResponse,
  getJson,
  postJson,
  sessionChangedEvent,
  sessionStorageKey,
  submitAuth,
  type AuthProductState,
  type AuthUser
} from "@/shared/api/auth";
import { AuthForm, AuthFormSubmitValues, AuthMode } from "@/shared/ui";
import {
  formatBillingPeriod,
  formatCatalogPrice,
  productPresentation,
  supportEmail
} from "@/features/catalog";
import {
  CheckoutAction,
  CheckoutAdapterStatus,
  getCheckoutAdapter
} from "./provider-adapters";
import { useCheckoutOwnership } from "./ownership";
type CheckoutIntentResponse = {
  product_state: AuthProductState;
  checkout: {
    amount_minor: number;
    amount: number;
    currency: string;
    action: CheckoutAction;
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
type AcceptDocumentResponse = {
  acceptance_id?: unknown;
  doc_type?: unknown;
};
const telegramLoginUrl = process.env.NEXT_PUBLIC_TELEGRAM_LOGIN_URL ?? "";
export function CheckoutClient({
  checkoutAdapterStatus = "disabled"
}: {
  checkoutAdapterStatus?: CheckoutAdapterStatus;
}) {
  const searchParams = useSearchParams();
  const initialProduct = searchParams.get("product");
  const initialAuthMode = searchParams.get("auth");
  const [selectedCode] = useState(initialProduct ?? "");
  const [catalogProducts, setCatalogProducts] = useState<CatalogProduct[]>([]);
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [catalogError, setCatalogError] = useState(false);
  const selectedProduct = useMemo(
    () => {
      if (catalogLoading || catalogError) {
        return undefined;
      }

      const matches = catalogProducts.filter(
        (product) => product.code === selectedCode
      );
      return matches.length === 1 ? matches[0] : undefined;
    },
    [catalogError, catalogLoading, catalogProducts, selectedCode]
  );
  const [mode, setMode] = useState<"login" | "register">(
    initialAuthMode === "login" ? "login" : "register"
  );
  const [autoRenew, setAutoRenew] = useState(false);
  const [recurrentConsent, setRecurrentConsent] = useState(false);
  const [recurringConsentAcceptanceId, setRecurringConsentAcceptanceId] =
    useState("");
  const [sessionToken, setSessionToken] = useState("");
  const [sessionUser, setSessionUser] = useState<AuthUser | null>(null);
  const [sessionResolved, setSessionResolved] = useState(false);
  const ownershipState = useCheckoutOwnership(sessionResolved, sessionToken);
  const [productState, setProductState] = useState<AuthProductState | null>(
    null
  );
  const [missingDocuments, setMissingDocuments] = useState<RequiredDocument[]>([]);
  const [documentConsentById, setDocumentConsentById] = useState<
    Record<string, boolean>
  >({});
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [sessionLoading, setSessionLoading] = useState(false);
  const feedbackRef = useRef<HTMLDivElement | null>(null);
  const previousSessionUserKeyRef = useRef("");
  const previousCheckoutContextKeyRef = useRef("");

  const invalidProduct =
    !catalogLoading &&
    !catalogError &&
    initialProduct !== null &&
    !selectedProduct;
  const needsAuthPrompt =
    !catalogLoading && !catalogError && !!selectedProduct && !sessionUser;
  const forceAuthPrompt =
    !catalogLoading &&
    !catalogError &&
    !invalidProduct &&
    initialAuthMode === "login" &&
    !sessionUser;
  const [authModalDismissed, setAuthModalDismissed] = useState(false);
  const showAuthModal =
    !catalogLoading &&
    !catalogError &&
    (needsAuthPrompt || forceAuthPrompt) &&
    !sessionLoading &&
    !authModalDismissed;
  const allMissingDocumentsAccepted =
    missingDocuments.length > 0 &&
    missingDocuments.every(
      (document) => documentConsentById[document.document_version_id]
    );
  const checkoutAdapterBlocked =
    checkoutAdapterStatus === "loading" || checkoutAdapterStatus === "failed";
  const sessionUserKey = sessionUser
    ? `${sessionUser.tenant_id}:${sessionUser.region}:${sessionUser.user_id}`
    : "";
  const checkoutContextKey = selectedProduct
    ? `${selectedProduct.code}:${selectedProduct.plan.code}`
    : "";

  function clearRecurringConsentEvidence() {
    setRecurringConsentAcceptanceId("");
  }

  useEffect(() => {
    let cancelled = false;

    async function loadCatalog() {
      try {
        const response = await getCatalogProducts();
        if (!cancelled) {
          setCatalogProducts(response.products);
        }
      } catch {
        if (!cancelled) {
          setCatalogProducts([]);
          setCatalogError(true);
        }
      } finally {
        if (!cancelled) {
          setCatalogLoading(false);
        }
      }
    }

    void loadCatalog();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    function syncStoredToken() {
      const storedToken = window.localStorage.getItem(sessionStorageKey) ?? "";
      setSessionResolved(true);
      if (storedToken) {
        setSessionLoading(true);
        setSessionToken(storedToken);
      } else {
        setSessionToken("");
        setSessionUser(null);
        setProductState(null);
        clearRecurringConsentEvidence();
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
        clearRecurringConsentEvidence();
        setSessionLoading(false);
        return;
      }

      setSessionLoading(true);

      try {
        const suffix = selectedCode
          ? `/api/auth/session?product=${encodeURIComponent(selectedCode)}`
          : "/api/auth/session";
        const payload = await getJson(
          suffix,
          sessionToken,
          decodeAuthSessionResponse
        );
        setSessionUser(payload.user);
        setProductState(payload.product_state ?? null);
        setNotice("");
      } catch {
        window.localStorage.removeItem(sessionStorageKey);
        window.dispatchEvent(new Event(sessionChangedEvent));
        setSessionToken("");
        setSessionUser(null);
        setProductState(null);
        clearRecurringConsentEvidence();
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
    const previousKey = previousSessionUserKeyRef.current;
    if (previousKey && previousKey !== sessionUserKey) {
      clearRecurringConsentEvidence();
      setRecurrentConsent(false);
    }
    previousSessionUserKeyRef.current = sessionUserKey;
  }, [sessionUserKey]);

  useEffect(() => {
    const previousKey = previousCheckoutContextKeyRef.current;
    if (previousKey && previousKey !== checkoutContextKey) {
      clearRecurringConsentEvidence();
      setRecurrentConsent(false);
    }
    previousCheckoutContextKeyRef.current = checkoutContextKey;
  }, [checkoutContextKey]);

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

    const detail = errorValue.detail;
    const detailRecord =
      typeof detail === "object" && detail !== null
        ? (detail as Record<string, unknown>)
        : null;
    if (
      detailRecord !== null &&
      detailRecord.code === "missing_required_documents" &&
      Array.isArray(detailRecord.documents)
    ) {
      const documents = detailRecord.documents.filter(isRequiredDocument);
      return documents.length === detailRecord.documents.length
        ? documents
        : null;
    }

    return null;
  }

  function isRequiredDocument(value: unknown): value is RequiredDocument {
    if (typeof value !== "object" || value === null) {
      return false;
    }
    const document = value as Record<string, unknown>;
    return (
      typeof document.document_version_id === "string" &&
      typeof document.doc_type === "string" &&
      typeof document.version === "string" &&
      typeof document.title === "string" &&
      typeof document.url_path === "string" &&
      typeof document.acceptance_text === "string" &&
      typeof document.acceptance_text_hash === "string"
    );
  }

  function apiErrorCode(errorValue: unknown): string | null {
    if (!(errorValue instanceof ApiError)) {
      return null;
    }
    const detail = errorValue.detail;
    if (typeof detail === "string") {
      return detail;
    }
    if (typeof detail === "object" && detail !== null && "code" in detail) {
      const code = (detail as Record<string, unknown>).code;
      if (typeof code === "string") {
        return code;
      }
    }
    return null;
  }

  function checkoutPreparationErrorMessage(errorValue: unknown): string {
    const code = apiErrorCode(errorValue);
    if (code === "automatic_renewal_not_permitted") {
      return "Выбранный тариф не поддерживает автопродление. Отключите автопродление или выберите другой тариф.";
    }
    if (code === "recurring_consent_required") {
      return "Для автопродления нужно принять актуальный документ о регулярных списаниях.";
    }
    if (code === "recurring_consent_invalid") {
      return "Согласие на регулярные списания устарело. Примите актуальный документ ещё раз.";
    }
    if (code === "invalid_acceptance_text_hash") {
      return "Текст согласия изменился. Обновите страницу и попробуйте ещё раз.";
    }
    if (code === "missing_required_documents") {
      return "Перед оплатой нужно принять актуальные юридические документы.";
    }

    if (errorValue instanceof ApiError && errorValue.status === 409) {
      if (
        errorValue.detail === "cloudpayments_public_terminal_id_missing" ||
        errorValue.detail === "cloudpayments_widget_mode_invalid"
      ) {
        return "Платёжный терминал настроен некорректно. Обратитесь в поддержку.";
      }
    }

    return "Не удалось подготовить оплату. Попробуйте ещё раз.";
  }

  async function authenticate(values: AuthFormSubmitValues) {
    setError("");
    setNotice("");

    setLoading(true);
    try {
      const payload = await submitAuth(values);
      window.localStorage.setItem(sessionStorageKey, payload.token);
      window.dispatchEvent(new Event(sessionChangedEvent));
      setSessionToken(payload.token);
      setSessionUser(payload.user);
      setMissingDocuments([]);
      setDocumentConsentById({});
      clearRecurringConsentEvidence();
      setRecurrentConsent(false);
      showNotice(
        values.mode === "register"
          ? "Аккаунт создан. Теперь можно перейти к оплате."
          : "Вход выполнен. Можно продолжить оформление."
      );
    } catch (requestError) {
      showError(authErrorMessage(requestError));
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
      clearRecurringConsentEvidence();
      setRecurrentConsent(false);
    }
  }

  async function goToPaymentResult(recurringAcceptanceIdOverride?: string) {
    if (productState?.status === "active") {
      return;
    }

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

    if (checkoutAdapterStatus === "loading") {
      showError("Платёжный виджет ещё загружается. Попробуйте через несколько секунд.");
      return;
    }

    if (checkoutAdapterStatus === "failed") {
      showError(
        "Не удалось загрузить платёжный виджет. Обновите страницу и попробуйте ещё раз."
      );
      return;
    }

    let checkoutIntent: CheckoutIntentResponse;
    try {
      const effectiveRecurringConsentAcceptanceId =
        recurringAcceptanceIdOverride ?? recurringConsentAcceptanceId;
      const checkoutPayload = {
        product: selectedProduct.code,
        plan_code: selectedProduct.plan.code,
        auto_renew: autoRenew,
        ...(autoRenew && effectiveRecurringConsentAcceptanceId
          ? {
              recurring_consent_acceptance_id:
                effectiveRecurringConsentAcceptanceId
            }
          : {})
      };
      const payload = await postJson<CheckoutIntentResponse>(
        "/api/auth/checkout-intent",
        checkoutPayload,
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
        if (
          documents.some((document) => document.doc_type === "recurring_consent")
        ) {
          clearRecurringConsentEvidence();
        }
        showError("Перед оплатой нужно принять актуальные юридические документы.");
        return;
      }

      if (apiErrorCode(requestError) === "recurring_consent_invalid") {
        clearRecurringConsentEvidence();
      }
      showError(checkoutPreparationErrorMessage(requestError));
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

    const checkoutAction = checkoutIntent.checkout.action;
    const checkoutAdapter = getCheckoutAdapter(checkoutAction.provider);
    if (!checkoutAdapter || !checkoutAdapter.isRequired()) {
      window.sessionStorage.removeItem("anytoolai_last_payment_result");
      showError("Платёжный провайдер недоступен. Обратитесь в поддержку.");
      return;
    }

    if (!checkoutAdapter.isReady()) {
      window.sessionStorage.removeItem("anytoolai_last_payment_result");
      showError(
        "Не удалось открыть платёжный виджет. Обновите страницу и попробуйте ещё раз."
      );
      return;
    }

    try {
      checkoutAdapter.start(checkoutAction, {
        productCode: selectedProduct.code,
        planCode: selectedProduct.plan.code,
        email: sessionUser.email,
        invoiceId: checkoutIntent.product_state.invoice_id ?? ""
      });
    } catch {
      window.sessionStorage.removeItem("anytoolai_last_payment_result");
      showError(
        "Не удалось открыть платёжный виджет. Обновите страницу и попробуйте ещё раз."
      );
      return;
    }
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
      let recurringAcceptanceId = "";
      for (const document of missingDocuments) {
        const acceptance = await postJson<AcceptDocumentResponse>(
          "/api/legal/acceptances",
          {
            document_version_id: document.document_version_id,
            acceptance_text_hash: document.acceptance_text_hash,
            entrypoint_type: "product",
            entrypoint_value: selectedProduct?.code ?? null,
            source_url: window.location.pathname + window.location.search,
            metadata: {
              plan_code: selectedProduct?.plan.code ?? null,
              auto_renew: autoRenew
            }
          },
          sessionToken
        );
        if (document.doc_type === "recurring_consent") {
          if (
            typeof acceptance.acceptance_id !== "string" ||
            acceptance.doc_type !== "recurring_consent"
          ) {
            throw new Error("recurring_acceptance_missing");
          }
          recurringAcceptanceId = acceptance.acceptance_id;
        }
      }

      if (
        autoRenew &&
        missingDocuments.some((document) => document.doc_type === "recurring_consent")
      ) {
        if (!recurringAcceptanceId) {
          throw new Error("recurring_acceptance_missing");
        }
        setRecurringConsentAcceptanceId(recurringAcceptanceId);
      }
      setMissingDocuments([]);
      setDocumentConsentById({});
      showNotice("Документы приняты. Продолжаем оформление оплаты.");
      await goToPaymentResult(recurringAcceptanceId || undefined);
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
    <AuthForm
      title="1. Вход или регистрация"
      badgeIcon={<ShieldCheck size={12} aria-hidden="true" />}
      initialMode={mode}
      modeOrder={["register", "login"]}
      prompt={
        needsAuthPrompt && !sessionLoading ? (
        <div className="notice">
          Чтобы продолжить оформление, войдите в аккаунт или зарегистрируйтесь.
        </div>
        ) : null
      }
      notice={notice}
      error={error}
      loading={loading}
      personalConsentError="Для регистрации нужно отдельное согласие на обработку персональных данных."
      offerConsentError="Для регистрации нужно принять условия оферты."
      includeCancellationLink
      telegramLoginUrl={telegramLoginUrl}
      telegramIcon={<MessageCircleMore size={16} aria-hidden="true" />}
      feedbackRef={feedbackRef}
      onModeChange={(nextMode: AuthMode) => setMode(nextMode)}
      onBeforeSubmit={() => {
        setError("");
        setNotice("");
      }}
      onValidationError={showError}
      onSubmit={authenticate}
    />
  );

  if (catalogLoading) {
    return (
      <section className="page-section compact">
        <div className="form-panel" role="status">
          Загрузка каталога...
        </div>
      </section>
    );
  }

  if (catalogError) {
    return (
      <section className="page-section compact">
        <div className="form-panel notice error" role="alert">
          Не удалось загрузить каталог. Обновите страницу и попробуйте ещё раз.
        </div>
      </section>
    );
  }

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
                onClick={() => setAuthModalDismissed(true)}
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
                <SelectedProductCard
                  product={selectedProduct}
                  state={productState}
                />
              ) : (
                <div className="form-panel checkout-equal-panel">
                  <h2>Выберите продукт</h2>
                  <p className="card-copy">
                    Откройте нужный сервис, чтобы увидеть тариф, бесплатный лимит и
                    перейти к оформлению.
                  </p>
                  <ProductCards
                    products={catalogProducts}
                    ownershipState={ownershipState}
                  />
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

                    {productState?.status !== "active" ? (
                      <>
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
                                    <Link
                                      className="inline-link"
                                      href={document.url_path}
                                      target="_blank"
                                      rel="noopener noreferrer"
                                    >
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
                                clearRecurringConsentEvidence();
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

                        {checkoutAdapterStatus === "failed" ? (
                          <div className="notice error">
                            Не удалось загрузить платёжный виджет. Обновите страницу и
                            попробуйте ещё раз.
                          </div>
                        ) : null}

                        {selectedProduct ? (
                          <button
                            className="btn-primary"
                            type="button"
                            onClick={() => void goToPaymentResult()}
                            disabled={
                              missingDocuments.length > 0 || checkoutAdapterBlocked
                            }
                          >
                            {checkoutAdapterStatus === "loading"
                              ? "Загрузка оплаты..."
                              : "Оплатить"}
                            <ArrowRight size={16} aria-hidden="true" />
                          </button>
                        ) : null}
                      </>
                    ) : null}

                    {productState?.status === "active" ? (
                      <Link className="btn-secondary" href="/ru/account">
                        Перейти в аккаунт
                        <ArrowRight size={15} aria-hidden="true" />
                      </Link>
                    ) : null}
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
                      onClick={() => setAuthModalDismissed(false)}
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
  product,
  state
}: {
  product: CatalogProduct;
  state: AuthProductState | null;
}) {
  const presentation = productPresentation[product.code];
  const Icon = presentation?.Icon ?? Sparkles;
  const productDescription = presentation?.description ?? product.description;

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
      {presentation?.type ? <span className="tool-tag">{presentation.type}</span> : null}
      <h2>{product.name}</h2>
      <p className="muted" style={{ margin: "0 0 8px" }}>
        {presentation?.tagline}
      </p>
      {productDescription ? <p className="card-copy">{productDescription}</p> : null}
      {presentation?.valuePoints ? (
        <ul className="check-list">
          {presentation.valuePoints.map((point) => (
            <li key={point}>{point}</li>
          ))}
        </ul>
      ) : null}
      <div className="price-line">
        <strong>
          {formatCatalogPrice(
            product.plan.price_amount_minor,
            product.plan.currency
          )}
        </strong>
        <span>/ {formatBillingPeriod(product.plan.billing_period)}</span>
      </div>
      <div className="button-row" style={{ marginTop: 0 }}>
        <span className="badge badge-live">
          Пробный период {product.plan.trial_days} дней
        </span>
        {presentation?.freeLimit ? (
          <span className="badge badge-running">{presentation.freeLimit}</span>
        ) : null}
      </div>
      {state?.status === "active" ? null : (
        <div className="button-row">
          <button className="btn-primary" type="button" onClick={scrollToForm}>
            Оформить
          </button>
        </div>
      )}
    </article>
  );
}

function SubscriptionState({
  product,
  state
}: {
  product?: CatalogProduct;
  state: AuthProductState | null;
}) {
  if (!product) {
    return (
      <div className="notice">
        Выберите продукт, чтобы увидеть статус подписки и перейти к оплате.
      </div>
    );
  }

  const presentation = productPresentation[product.code];
  const status = state?.status ?? "inactive";
  const planName =
    (state?.status === "active" || state?.status === "pending") &&
    state.plan_name
      ? state.plan_name
      : product.plan.name;
  const statusText =
    status === "active"
      ? "Подписка активна"
      : status === "pending"
        ? "Платёж ожидает подтверждения"
        : "Подписка не активна";

  return (
    <div className="notice">
      <strong style={{ color: "var(--txt)" }}>{planName}</strong>
      <br />
      Статус: {statusText}
      <br />
      Стоимость: {formatCatalogPrice(
        product.plan.price_amount_minor,
        product.plan.currency
      )} / {formatBillingPeriod(product.plan.billing_period)}
      <br />
      Бесплатный лимит: {presentation?.freeLimit ?? "—"}
      {state?.expires_at ? (
        <>
          <br />
          Действует до: {new Date(state.expires_at).toLocaleDateString("ru-RU")}
        </>
      ) : null}
      {status === "active" ? (
        <>
          <br />
          Доступ уже активен. Управление доступно в аккаунте.
        </>
      ) : null}
    </div>
  );
}
