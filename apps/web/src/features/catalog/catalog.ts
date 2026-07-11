import {
  FileText,
  Languages,
  MessageSquareQuote,
  ShieldCheck,
  Sparkles,
  WandSparkles
} from "lucide-react";

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

export type ProductCode = "document-summary" | "prompt-optimizer";

export type Product = {
  code: ProductCode;
  name: string;
  type: string;
  tagline: string;
  description: string;
  valuePoints: string[];
  freeLimit: string;
  plan: {
    code: string;
    name: string;
    priceRub: number;
    period: "month";
    trialDays: number;
    paymentDescription: string;
  };
  Icon: typeof FileText;
};

export const products: Product[] = [
  {
    code: "document-summary",
    name: "Document Summary",
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
    plan: {
      code: "document-summary-pro",
      name: "Document Summary Pro",
      priceRub: 990,
      period: "month",
      trialDays: 7,
      paymentDescription: "Подписка Document Summary Pro на 1 месяц"
    },
    Icon: FileText
  },
  {
    code: "prompt-optimizer",
    name: "Prompt Optimizer",
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
    plan: {
      code: "prompt-optimizer-pro",
      name: "Prompt Optimizer Pro",
      priceRub: 990,
      period: "month",
      trialDays: 7,
      paymentDescription: "Подписка Prompt Optimizer Pro на 1 месяц"
    },
    Icon: WandSparkles
  }
];

export const platformFacts = [
  {
    label: "Продукта",
    value: "2",
    detail: "Document Summary и Prompt Optimizer",
    Icon: Sparkles
  },
  {
    label: "Бесплатный период",
    value: "7",
    detail: "дней до начала оплаты",
    Icon: ShieldCheck
  },
  {
    label: "Бесплатный доступ",
    value: "3 / 50",
    detail: "лимиты для двух сервисов",
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

export function findProduct(code: string | null | undefined): Product | undefined {
  if (!code) {
    return undefined;
  }

  return products.find((product) => product.code === code);
}

export function formatRubles(value: number): string {
  return new Intl.NumberFormat("ru-RU").format(value) + " ₽";
}
