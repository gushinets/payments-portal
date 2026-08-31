import {
  FileText,
  Languages,
  MessageSquareQuote,
  ShieldCheck,
  Sparkles,
  WandSparkles
} from "lucide-react";

export { findProduct, products } from "./legacy";
export type { Product, ProductCode } from "./legacy";

export const supportEmail = "support@any-tool-ai.ru";

export const seller = {
  name: "ИП Говоров Роман Стальевич",
  inn: "143509640374",
  ogrnip: "314547633100101",
  address: "630091 , Новосибирская область, г. Новосибирск"
};

export type PaymentMethod = {
  code: string;
  label: string;
  href?: string;
};

export const paymentMethods: PaymentMethod[] = [
  { code: "card", label: "Банковская карта" },
  { code: "sbp", label: "СБП" },
  {
    code: "tpay",
    label: "T-Pay",
    href: "https://www.tbank.ru/"
  },
  { code: "mir", label: "Мир" }
];

export type ProductPresentation = {
  type: string;
  tagline: string;
  description: string;
  valuePoints: string[];
  freeLimit: string;
  Icon: typeof FileText;
};

export const productPresentation: Record<string, ProductPresentation> = {
  "document-summary": {
    type: "Chrome extension",
    tagline: "Мгновенное краткое содержание любого документа",
    description:
      "Расширение помогает быстро получать summary документов и веб-страниц без лишних ручных действий.",
    valuePoints: [
      "Три режима: полное summary, короткое summary и тезисы",
      "Работает с PDF, TXT и веб-страницами",
      "Определяет язык документа и отвечает на нём же",
      "Позволяет экспортировать результат в PDF",
      "Файлы не сохраняются на серверах"
    ],
    freeLimit: "3 summary в месяц",
    Icon: FileText
  },
  "prompt-optimizer": {
    type: "Chrome extension",
    tagline: "Улучшение промптов для ИИ в один клик",
    description:
      "Расширение улучшает промпты прямо в привычном интерфейсе и показывает, что именно стало лучше.",
    valuePoints: [
      "Работает поверх ChatGPT, Claude, Perplexity, Groq и DeepSeek",
      "Показывает, что именно улучшено в промпте",
      "Возвращает улучшенный промпт обратно в чат одним кликом",
      "Сохраняет готовые промпты в библиотеке"
    ],
    freeLimit: "50 оптимизаций в месяц",
    Icon: WandSparkles
  }
};

export const platformFacts = [
  {
    label: "Каталог",
    value: "RU",
    detail: "Актуальные предложения загружаются из API",
    Icon: Sparkles
  },
  {
    label: "Тарифы",
    value: "API",
    detail: "Цена и условия указаны в карточках",
    Icon: ShieldCheck
  },
  {
    label: "Доступ",
    value: "1 аккаунт",
    detail: "Статус подписки проверяется перед оформлением",
    Icon: FileText
  },
  {
    label: "Локализация",
    value: "RU",
    detail: "юридические документы и оплата",
    Icon: Languages
  }
];

export const platformHighlights = [
  {
    title: "Простой старт",
    description:
      "Оформление подписки и юридические документы собраны в одном понятном портале.",
    Icon: Sparkles
  },
  {
    title: "Один аккаунт",
    description:
      "Единый вход для сервисов готовится. На этом этапе можно оформить доступ по email.",
    Icon: MessageSquareQuote
  },
  {
    title: "Безопасная оплата",
    description:
      "Платёж подтверждается через платёжного партнёра, а данные карт не хранятся на стороне платформы.",
    Icon: ShieldCheck
  }
];

export function formatRubles(value: number): string {
  return new Intl.NumberFormat("ru-RU").format(value) + " ₽";
}

export function formatCatalogPrice(
  priceAmountMinor: number,
  currency: string
): string {
  if (currency.toUpperCase() !== "RUB") {
    throw new Error("unsupported_catalog_currency");
  }

  return formatRubles(priceAmountMinor / 100);
}

export function formatBillingPeriod(period: string): string {
  const labels: Record<string, string> = {
    day: "день",
    days: "дней",
    week: "неделю",
    weeks: "недель",
    month: "месяц",
    months: "месяцев",
    year: "год",
    years: "лет",
    annual: "год",
    yearly: "год"
  };

  return labels[period] ?? period;
}
